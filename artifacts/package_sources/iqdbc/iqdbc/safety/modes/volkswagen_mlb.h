#pragma once

#include "iqdbc/safety/declarations.h"
#include "iqdbc/safety/modes/volkswagen_common.h"

// The shared -3.5 m/s^2 MQB floor faults the Audi Q5 ACC ECU and needs an ignition cycle to clear,
// so MLB carries its own stricter limit instead of VW_IQ_MIN_LONG_ACCEL.
#define VOLKSWAGEN_MLB_MIN_LONG_ACCEL -2950

// Both 0 m/s^2 and the sentinel one increment above the range max read as "no request" to the MLB
// drivetrain coordinator. Accept a small band around the sentinel (+/-15 raw = +/-0.075 m/s^2)
// so a rounding difference on the sending side cannot silently block the whole ACC_01 stream.
#define VOLKSWAGEN_MLB_INACTIVE_ACCEL_TOLERANCE 15

static bool volkswagen_mlb_no_ecan = false;

static bool volkswagen_mlb_long_accel_check(int desired_accel) {
  int inactive_delta = desired_accel - VW_IQ_INACTIVE_LONG_ACCEL;
  bool inactive = ((inactive_delta >= -VOLKSWAGEN_MLB_INACTIVE_ACCEL_TOLERANCE) &&
                   (inactive_delta <= VOLKSWAGEN_MLB_INACTIVE_ACCEL_TOLERANCE)) || (desired_accel == 0);
  if (inactive) {
    return false;
  }
  if (!controls_allowed) {
    return true;
  }
  if (gas_pressed_prev && !volkswagen_allow_long_accel_with_gas_pressed) {
    return true;
  }
  return (desired_accel > VW_IQ_MAX_LONG_ACCEL) || (desired_accel < VOLKSWAGEN_MLB_MIN_LONG_ACCEL);
}

static safety_config volkswagen_mlb_init(uint16_t param) {
  // Transmit of LS_01 is allowed on bus 0 and 2 to keep compatibility with gateway and camera integration
  static const CanMsg VOLKSWAGEN_MLB_STOCK_TX_MSGS[] = {{MSG_HCA_01, 0, 8, .check_relay = true}, {MSG_LDW_02, 0, 8, .check_relay = true},
                                                        {MSG_LS_01, 0, 4, .check_relay = false}, {MSG_LS_01, 2, 4, .check_relay = false}};

  static const CanMsg VOLKSWAGEN_MLB_LONG_TX_MSGS[] = {{MSG_HCA_01, 0, 8, .check_relay = true}, {MSG_LDW_02, 0, 8, .check_relay = true},
                                                       {MSG_ACC_01, 0, 8, .check_relay = true}, {MSG_ACC_02, 0, 8, .check_relay = true}};

  static const CanMsg VOLKSWAGEN_MLB_NO_ECAN_TX_MSGS[] = {{MSG_HCA_01, 1, 8, .check_relay = true}, {MSG_LDW_02, 1, 8, .check_relay = true},
                                                          {MSG_LS_01, 1, 4, .check_relay = false}};

  static RxCheck volkswagen_mlb_rx_checks[] = {
    // TODO: implement checksum validation
    {.msg = {{MSG_ESP_03, 0, 8, 50U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_LH_EPS_03, 0, 8, 100U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_ESP_05, 0, 8, 50U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_ACC_05, 2, 8, 50U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, {MSG_TSK_02, 0, 8, 50U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }}},
    {.msg = {{MSG_MOTOR_03, 0, 8, 100U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_LS_01, 0, 4, 10U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
  };

  static RxCheck volkswagen_mlb_no_ecan_rx_checks[] = {
    {.msg = {{MSG_ESP_03, 1, 8, 50U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_LH_EPS_03, 1, 8, 100U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_ESP_05, 1, 8, 50U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_TSK_02, 1, 8, 50U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_MOTOR_03, 1, 8, 100U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{MSG_LS_01, 1, 4, 10U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
  };

  volkswagen_common_init();
  volkswagen_mlb_no_ecan = GET_FLAG(param, FLAG_VOLKSWAGEN_MLB_NO_ECAN);

#ifdef ALLOW_DEBUG
  volkswagen_longitudinal = GET_FLAG(param, FLAG_VOLKSWAGEN_LONG_CONTROL);
  volkswagen_allow_long_accel_with_gas_pressed = GET_FLAG(param, FLAG_VOLKSWAGEN_ALLOW_LONG_ACCEL_WITH_GAS_PRESSED);
#else
  SAFETY_UNUSED(param);
#endif

  return volkswagen_longitudinal ? BUILD_SAFETY_CFG(volkswagen_mlb_rx_checks, VOLKSWAGEN_MLB_LONG_TX_MSGS) : \
         volkswagen_mlb_no_ecan    ? BUILD_SAFETY_CFG(volkswagen_mlb_no_ecan_rx_checks, VOLKSWAGEN_MLB_NO_ECAN_TX_MSGS) : \
                                     BUILD_SAFETY_CFG(volkswagen_mlb_rx_checks, VOLKSWAGEN_MLB_STOCK_TX_MSGS);
}

static void volkswagen_mlb_rx_hook(const CANPacket_t *msg) {
  if (msg->bus == (volkswagen_mlb_no_ecan ? 1U : 0U)) {
    // Check all wheel speeds for any movement
    // Signals: ESP_03.ESP_[VL|VR|HL|HR]_Radgeschw
    if (msg->addr == MSG_ESP_03) {
      uint32_t speed = 0;
      speed += ((msg->data[3] & 0xFU) << 8) | msg->data[2];   // FL
      speed += (msg->data[4] << 4) | (msg->data[3] >> 4);     // FR
      speed += ((msg->data[6] & 0xFU) << 8) | msg->data[5];   // RL
      speed += (msg->data[7] << 4) | (msg->data[6] >> 4);     // RR
      vehicle_moving = speed > 0U;
    }

    // Update driver input torque
    if (msg->addr == MSG_LH_EPS_03) {
      update_sample(&torque_driver, volkswagen_mlb_mqb_driver_input_torque(msg));
    }

    if (msg->addr == MSG_LS_01) {
      // If using openpilot longitudinal, the stock ACC coordinator is relayed out, so the stalk main
      // switch is the only remaining source of truth. Enter controls on falling edge of Set or Resume.
      // Signal: LS_01.LS_Hauptschalter
      // Signal: LS_01.LS_Tip_Setzen
      // Signal: LS_01.LS_Tip_Wiederaufnahme
      if (volkswagen_longitudinal) {
        acc_main_on = GET_BIT(msg, 12U);

        bool set_button = GET_BIT(msg, 16U);
        bool resume_button = GET_BIT(msg, 19U);
        if ((volkswagen_set_button_prev && !set_button) || (volkswagen_resume_button_prev && !resume_button)) {
          controls_allowed = acc_main_on;
        }
        volkswagen_set_button_prev = set_button;
        volkswagen_resume_button_prev = resume_button;

        if (!acc_main_on) {
          controls_allowed = false;
        }
      }

      // Always exit controls on rising edge of Cancel
      // Signal: LS_01.LS_Abbrechen
      if (GET_BIT(msg, 13U)) {
        controls_allowed = false;
      }
    }

    // Signal: Motor_03.MO_Fahrpedalrohwert_01
    // Signal: Motor_03.MO_BLS -- MO_Fahrer_bremst (bit 35) sticks on real MLB hardware
    if (msg->addr == MSG_MOTOR_03) {
      gas_pressed = msg->data[6] != 0U;
      volkswagen_brake_pedal_switch = GET_BIT(msg, 34U);
    }

    if (msg->addr == MSG_ESP_05) {
      volkswagen_brake_pressure_detected = GET_BIT(msg, 26U);
    }

    brake_pressed = volkswagen_brake_pedal_switch || volkswagen_brake_pressure_detected;

    if ((msg->addr == MSG_TSK_02) && !volkswagen_longitudinal) {
      // When using stock ACC, enter controls on rising edge of stock ACC engage, exit on disengage
      // Always exit controls on main switch off
      // Signal: TSK_02.TSK_Status
      int acc_status = (msg->data[2] & 0x3U);
      bool cruise_engaged = (acc_status == 1) || (acc_status == 2);
      acc_main_on = cruise_engaged || (acc_status == 0);
      pcm_cruise_check(cruise_engaged);
       if (!acc_main_on) {
          controls_allowed = false;
       }
    }
  }

  if (msg->bus == 2U) {
    // TODO: See if there's a bus-agnostic TSK message we can use instead
    if ((msg->addr == MSG_ACC_05) && !volkswagen_longitudinal) {
      // When using stock ACC, enter controls on rising edge of stock ACC engage, exit on disengage
      // Always exit controls on main switch off
      // Signal: ACC_05.ACC_Status_ACC
      int acc_status = (msg->data[7] & 0xEU) >> 1;
      bool cruise_engaged = (acc_status == 3) || (acc_status == 4) || (acc_status == 5);
      acc_main_on = cruise_engaged || (acc_status == 2);

      pcm_cruise_check(cruise_engaged);

      if (!acc_main_on) {
        controls_allowed = false;
      }
    }
  }
}

static bool volkswagen_mlb_tx_hook(const CANPacket_t *msg) {
  // lateral limits
  const TorqueSteeringLimits VOLKSWAGEN_MLB_STEERING_LIMITS = {
    .max_torque = 300,             // 3.0 Nm (EPS side max of 3.0Nm with fault if violated)
    .max_rt_delta = 169,           // 10 max rate up * 50Hz send rate * 250000 RT interval / 1000000 = 112.5 ; 112.5 * 1.5 for safety pad = 168.75
    .max_rate_up = 9,              // 5.0 Nm/s RoC limit (EPS rack has own soft-limit of 5.0 Nm/s)
    .max_rate_down = 10,           // 5.0 Nm/s RoC limit (EPS rack has own soft-limit of 5.0 Nm/s)
    .driver_torque_allowance = 80,
    .driver_torque_multiplier = 3,
    .type = TorqueDriverLimited,
  };

  bool tx = true;

  // Safety check for HCA_01 Heading Control Assist torque
  if (msg->addr == MSG_HCA_01) {
    int desired_torque = volkswagen_mlb_mqb_steering_control_torque(msg);

    int steer_status = msg->data[4] & 0xFU;
    bool steer_req = (steer_status == 5) || (steer_status == 7);

    if (steer_torque_cmd_checks(desired_torque, steer_req, VOLKSWAGEN_MLB_STEERING_LIMITS)) {
      tx = false;
    }
  }

  // Safety check for ACC_01 acceleration request
  // Signal: ACC_01.ACC_Sollbeschleunigung (acceleration in m/s^2, scale 0.005, offset -7.22)
  // To avoid floating point math, scale upward and compare to pre-scaled safety m/s^2 boundaries
  if (msg->addr == MSG_ACC_01) {
    int desired_accel = ((((msg->data[4] & 0x07U) << 8) | msg->data[3]) * 5U) - 7220U;

    if (volkswagen_mlb_long_accel_check(desired_accel)) {
      tx = false;
    }
  }

  // FORCE CANCEL: ensuring that only the cancel button press is sent when controls are off.
  // This avoids unintended engagements while still allowing resume spam
  if ((msg->addr == MSG_LS_01) && !controls_allowed) {
    // disallow resume and set: bits 16 and 19
    if (GET_BIT(msg, 16U) || GET_BIT(msg, 19U)) {
      tx = false;
    }
  }

  return tx;
}

// TODO: rename these functions to MXB or something
const safety_hooks volkswagen_mlb_hooks = {
  .init = volkswagen_mlb_init,
  .rx = volkswagen_mlb_rx_hook,
  .tx = volkswagen_mlb_tx_hook,
  .get_counter = volkswagen_mqb_meb_get_counter,
  .get_checksum = volkswagen_mqb_meb_get_checksum,
  .compute_checksum = volkswagen_mqb_meb_compute_crc,
};
