#pragma once

#include "iqdbc/safety/declarations.h"
#include "iqdbc/safety/modes/chrysler.h"

#define CHRYSLER_CUSW_BRAKE_1        0x1E4U
#define CHRYSLER_CUSW_BRAKE_3        0x1E8U
#define CHRYSLER_CUSW_EPS_STATUS     0x1ECU
#define CHRYSLER_CUSW_ACCEL_GAS      0x1FEU
#define CHRYSLER_CUSW_ACC_CONTROL    0x2ECU
#define CHRYSLER_CUSW_LKAS_COMMAND   0x1F6U
#define CHRYSLER_CUSW_DAS_6          0x5DCU
#define CHRYSLER_CUSW_CRUISE_BUTTONS 0x2FAU

static safety_config chrysler_cusw_init(uint16_t param) {
  SAFETY_UNUSED(param);

  static const CanMsg CHRYSLER_CUSW_TX_MSGS[] = {
    {CHRYSLER_CUSW_LKAS_COMMAND, 0, 4, .check_relay = true},
    {CHRYSLER_CUSW_DAS_6, 0, 4, .check_relay = true},
    {CHRYSLER_CUSW_CRUISE_BUTTONS, 0, 3, .check_relay = false},
  };

  static RxCheck chrysler_cusw_rx_checks[] = {
    {.msg = {{CHRYSLER_CUSW_BRAKE_1, 0, 8, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{CHRYSLER_CUSW_BRAKE_3, 0, 5, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{CHRYSLER_CUSW_EPS_STATUS, 0, 8, 100U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{CHRYSLER_CUSW_ACCEL_GAS, 0, 5, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{CHRYSLER_CUSW_ACC_CONTROL, 0, 8, 50U, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
  };

  return BUILD_SAFETY_CFG(chrysler_cusw_rx_checks, CHRYSLER_CUSW_TX_MSGS);
}

static void chrysler_cusw_rx_hook(const CANPacket_t *msg) {
  if (msg->bus == 0U) {
    if (msg->addr == CHRYSLER_CUSW_EPS_STATUS) {
      int torque_meas_new = ((msg->data[3] & 0xFU) << 8) + msg->data[4] - 2048U;
      update_sample(&torque_meas, torque_meas_new);
    }

    if (msg->addr == CHRYSLER_CUSW_ACC_CONTROL) {
      bool cruise_engaged = GET_BIT(msg, 7U);
      pcm_cruise_check(cruise_engaged);
    }

    if (msg->addr == CHRYSLER_CUSW_BRAKE_1) {
      vehicle_moving = (((msg->data[4] & 0x7U) << 8) + msg->data[5]) != 0U;
    }

    if (msg->addr == CHRYSLER_CUSW_ACCEL_GAS) {
      gas_pressed = msg->data[1] != 0U;
    }

    if (msg->addr == CHRYSLER_CUSW_BRAKE_3) {
      brake_pressed = GET_BIT(msg, 18U);
    }
  }
}

static bool chrysler_cusw_tx_hook(const CANPacket_t *msg) {
  const TorqueSteeringLimits CHRYSLER_CUSW_STEERING_LIMITS = {
    .max_torque = 250,  // some CUSW EPS fault before reaching 261
    .max_rt_delta = 150,
    .max_rate_up = 4,
    .max_rate_down = 4,
    .max_torque_error = 80,
    .type = TorqueMotorLimited,
  };

  bool tx = true;

  if (msg->addr == CHRYSLER_CUSW_LKAS_COMMAND) {
    int desired_torque = ((msg->data[0]) << 3) | ((msg->data[1] & 0xE0U) >> 5);
    desired_torque -= 1024;

    const bool steer_req = GET_BIT(msg, 12U);
    if (steer_torque_cmd_checks(desired_torque, steer_req, CHRYSLER_CUSW_STEERING_LIMITS)) {
      tx = false;
    }
  }

  if (msg->addr == CHRYSLER_CUSW_CRUISE_BUTTONS) {
    const bool is_cancel = GET_BIT(msg, 0U);
    const bool is_resume = GET_BIT(msg, 4U);
    const bool allowed = is_cancel || (is_resume && controls_allowed);
    if (!allowed) {
      tx = false;
    }
  }

  return tx;
}

static uint8_t chrysler_cusw_get_counter(const CANPacket_t *msg) {
  int counter_byte = GET_LEN(msg) - 2U;
  return (uint8_t)(msg->data[counter_byte] & 0xFU);
}

const safety_hooks chrysler_cusw_hooks = {
  .init = chrysler_cusw_init,
  .rx = chrysler_cusw_rx_hook,
  .tx = chrysler_cusw_tx_hook,
  .get_counter = chrysler_cusw_get_counter,
  .get_checksum = chrysler_get_checksum,
  .compute_checksum = chrysler_compute_checksum,
};
