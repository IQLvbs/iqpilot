/*
 * Copyright © IQ.Lvbs, a part of Project Teal Lvbs.
 * All Rights Reserved.
 * Licensed under: https://konn3kt.com/tos
 */

#pragma once

#include "iqdbc/safety/declarations.h"

#define TESLA_LEGACY_FLAG_EXTERNAL_PANDA 4U
#define TESLA_LEGACY_FLAG_HW1 8U
#define TESLA_LEGACY_FLAG_HW2 16U
#define TESLA_LEGACY_FLAG_HW3 32U

#define TESLA_LEGACY_ADDR_ESP_B 0x155U
#define TESLA_LEGACY_ADDR_BRAKE_MESSAGE 0x20aU
#define TESLA_LEGACY_ADDR_BRAKE_MESSAGE_PT 0x1f8U
#define TESLA_LEGACY_ADDR_DI_STATE 0x368U
#define TESLA_LEGACY_ADDR_DI_STATE_PT 0x256U
#define TESLA_LEGACY_ADDR_EPAS_SYS_STATUS 0x370U
#define TESLA_LEGACY_ADDR_DAS_STEERING_CONTROL 0x488U
#define TESLA_LEGACY_ADDR_APS_EAC_MONITOR 0x27dU
#define TESLA_LEGACY_ADDR_DAS_CONTROL 0x2b9U
#define TESLA_LEGACY_ADDR_DAS_CONTROL_PT 0x2bfU
#define TESLA_LEGACY_ADDR_DI_TORQUE1 0x106U
#define TESLA_LEGACY_ADDR_DI_TORQUE1_HW1 0x108U

static bool tesla_legacy_external_panda = false;
static bool tesla_legacy_hw1 = false;

static uint8_t tesla_legacy_chassis_bus = 0U;
static unsigned int tesla_legacy_das_control_addr = TESLA_LEGACY_ADDR_DAS_CONTROL_PT;
static unsigned int tesla_legacy_di_torque1_addr = TESLA_LEGACY_ADDR_DI_TORQUE1;

static bool tesla_legacy_stock_aeb = false;
static bool tesla_legacy_stock_lkas = false;
static bool tesla_legacy_stock_lkas_prev = false;

static void tesla_legacy_rx_hook(const CANPacket_t *msg) {
  if (!tesla_legacy_external_panda && (msg->bus == 0U) && (msg->addr == TESLA_LEGACY_ADDR_EPAS_SYS_STATUS)) {
    const int angle_meas_new = (((msg->data[4] & 0x3FU) << 8) | msg->data[5]) - 8192U;
    update_sample(&angle_meas, angle_meas_new);

    const int hands_on_level = msg->data[4] >> 6;
    const int eac_status = msg->data[6] >> 5;
    const int eac_error_code = msg->data[2] >> 4;

    steering_disengage = (hands_on_level >= 3) || ((eac_status == 0) && (eac_error_code == 9));
  }

  if (!tesla_legacy_external_panda && (msg->bus == tesla_legacy_chassis_bus) && (msg->addr == TESLA_LEGACY_ADDR_ESP_B)) {
    float speed = ((msg->data[6] | (msg->data[5] << 8)) * 0.01) * KPH_TO_MS;
    UPDATE_VEHICLE_SPEED(speed);
  }

  if ((tesla_legacy_external_panda || tesla_legacy_hw1) && (msg->bus == 0U) && (msg->addr == tesla_legacy_di_torque1_addr)) {
    gas_pressed = msg->data[6] != 0U;
  }

  if ((tesla_legacy_external_panda && (msg->bus == 0U) && (msg->addr == TESLA_LEGACY_ADDR_BRAKE_MESSAGE_PT)) ||
      (!tesla_legacy_external_panda && (msg->bus == tesla_legacy_chassis_bus) && (msg->addr == TESLA_LEGACY_ADDR_BRAKE_MESSAGE))) {
    brake_pressed = (((msg->data[0] & 0x0CU) >> 2) != 1U);
  }

  if ((tesla_legacy_external_panda && (msg->bus == 0U) && (msg->addr == TESLA_LEGACY_ADDR_DI_STATE_PT)) ||
      (!tesla_legacy_external_panda && (msg->bus == tesla_legacy_chassis_bus) && (msg->addr == TESLA_LEGACY_ADDR_DI_STATE))) {
    int cruise_state = (msg->data[1] >> 4) & 0x07U;
    bool cruise_engaged = (cruise_state == 2) ||
                          (cruise_state == 3) ||
                          (cruise_state == 4) ||
                          (cruise_state == 6) ||
                          (cruise_state == 7);
    vehicle_moving = cruise_state != 3;
    pcm_cruise_check(cruise_engaged);
  }

  if (msg->bus == 2U) {
    if ((tesla_legacy_external_panda || tesla_legacy_hw1) && (msg->addr == tesla_legacy_das_control_addr)) {
      tesla_legacy_stock_aeb = (msg->data[2] & 0x03U) == 1U;
    }

    if (!tesla_legacy_external_panda && (msg->addr == TESLA_LEGACY_ADDR_DAS_STEERING_CONTROL)) {
      int steering_control_type = msg->data[2] >> 6;
      bool tesla_legacy_stock_lkas_now = steering_control_type == 2;

      if (tesla_legacy_stock_lkas_now && !tesla_legacy_stock_lkas_prev && !is_lat_active()) {
        tesla_legacy_stock_lkas = true;
      }
      if (!tesla_legacy_stock_lkas_now) {
        tesla_legacy_stock_lkas = false;
      }
      tesla_legacy_stock_lkas_prev = tesla_legacy_stock_lkas_now;
    }
  }
}

static bool tesla_legacy_tx_hook(const CANPacket_t *msg) {
  const AngleSteeringLimits TESLA_LEGACY_STEERING_LIMITS = {
    .max_angle = 3600,
    .angle_deg_to_can = 10,
    .frequency = 50U,
  };

  // NOTE: based off TESLA_MODEL_S_HW3 to match the car controller
  const AngleSteeringParams TESLA_LEGACY_STEERING_PARAMS = {
    .slip_factor = -0.0005666493436310427,
    .steer_ratio = 15.,
    .wheelbase = 2.96,
  };

  const LongitudinalLimits TESLA_LEGACY_LONG_LIMITS = {
    .max_accel = 425,
    .min_accel = 288,
    .inactive_accel = 375,
    .zero_accel = 375,
  };

  bool tx = true;
  bool violation = false;

  if (!tesla_legacy_external_panda && (msg->addr == TESLA_LEGACY_ADDR_DAS_STEERING_CONTROL)) {
    int raw_angle_can = ((msg->data[0] & 0x7FU) << 8) | msg->data[1];
    int desired_angle = raw_angle_can - 16384;
    int steer_control_type = msg->data[2] >> 6;
    bool steer_control_enabled = steer_control_type == 1;

    if (steer_angle_cmd_checks_vm(desired_angle, steer_control_enabled, TESLA_LEGACY_STEERING_LIMITS, TESLA_LEGACY_STEERING_PARAMS)) {
      violation = true;
    }

    bool valid_steer_control_type = (steer_control_type == 0) ||
                                    (steer_control_type == 1);
    if (!valid_steer_control_type) {
      violation = true;
    }

    if (tesla_legacy_stock_lkas) {
      violation = true;
    }
  }

  if ((tesla_legacy_external_panda || tesla_legacy_hw1) && (msg->addr == tesla_legacy_das_control_addr)) {
    int aeb_event = msg->data[2] & 0x03U;
    if (aeb_event != 0) {
      violation = true;
    }

    if (tesla_legacy_stock_aeb) {
      violation = true;
    }

    int raw_accel_max = ((msg->data[6] & 0x1FU) << 4) | (msg->data[5] >> 4);
    int raw_accel_min = ((msg->data[5] & 0x0FU) << 5) | (msg->data[4] >> 3);

    // Both limits below zero could let the car reverse after coming to a standstill
    if ((raw_accel_max < TESLA_LEGACY_LONG_LIMITS.inactive_accel) && (raw_accel_min < TESLA_LEGACY_LONG_LIMITS.inactive_accel)) {
      violation = true;
    }

    violation |= longitudinal_accel_checks(raw_accel_max, TESLA_LEGACY_LONG_LIMITS);
    violation |= longitudinal_accel_checks(raw_accel_min, TESLA_LEGACY_LONG_LIMITS);
  }

  if (violation) {
    tx = false;
  }

  return tx;
}

static bool tesla_legacy_fwd_hook(int bus_num, int addr) {
  bool block_msg = false;

  if (bus_num == 2) {
    if (!tesla_legacy_external_panda && !tesla_legacy_hw1 && (addr == (int)TESLA_LEGACY_ADDR_APS_EAC_MONITOR)) {
      block_msg = true;
    }

    if (!tesla_legacy_external_panda && (addr == (int)TESLA_LEGACY_ADDR_DAS_STEERING_CONTROL) && !tesla_legacy_stock_lkas) {
      block_msg = true;
    }

    if ((tesla_legacy_external_panda || tesla_legacy_hw1) && (addr == (int)tesla_legacy_das_control_addr) && !tesla_legacy_stock_aeb) {
      block_msg = true;
    }
  }

  return block_msg;
}

static safety_config tesla_legacy_init(uint16_t param) {
  tesla_legacy_external_panda = GET_FLAG(param, TESLA_LEGACY_FLAG_EXTERNAL_PANDA);
  tesla_legacy_hw1 = GET_FLAG(param, TESLA_LEGACY_FLAG_HW1);
  const bool tesla_legacy_hw2 = GET_FLAG(param, TESLA_LEGACY_FLAG_HW2);
  const bool tesla_legacy_hw3 = GET_FLAG(param, TESLA_LEGACY_FLAG_HW3);

  tesla_legacy_stock_aeb = false;
  tesla_legacy_stock_lkas = false;
  tesla_legacy_stock_lkas_prev = false;
  tesla_legacy_chassis_bus = 0U;
  tesla_legacy_di_torque1_addr = TESLA_LEGACY_ADDR_DI_TORQUE1;
  tesla_legacy_das_control_addr = tesla_legacy_external_panda ? TESLA_LEGACY_ADDR_DAS_CONTROL_PT : TESLA_LEGACY_ADDR_DAS_CONTROL;

  static const CanMsg TESLA_LEGACY_TX_MSGS[] = {
    {0x488, 0, 4, .check_relay = true, .disable_static_blocking = true},
    {0x27D, 0, 3, .check_relay = true, .disable_static_blocking = true},
  };

  static const CanMsg TESLA_LEGACY_PT_TX_MSGS[] = {
    {0x2bf, 0, 8, .check_relay = true, .disable_static_blocking = true},
  };

  static const CanMsg TESLA_LEGACY_HW1_TX_MSGS[] = {
    {0x488, 0, 4, .check_relay = true, .disable_static_blocking = true},
    {0x2b9, 0, 8, .check_relay = true, .disable_static_blocking = true},
  };

  safety_config ret;
  if (tesla_legacy_external_panda && (tesla_legacy_hw3 || tesla_legacy_hw2)) {
    static RxCheck tesla_legacy_pt_rx_checks[] = {
      {.msg = {{0x106, 0, 8, 100U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x1f8, 0, 8, 50U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x2bf, 2, 8, 25U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x256, 0, 8, 10U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
    };
    SET_RX_CHECKS(tesla_legacy_pt_rx_checks, ret);
    SET_TX_MSGS(TESLA_LEGACY_PT_TX_MSGS, ret);
  } else if (tesla_legacy_hw3) {
    static RxCheck tesla_legacy_hw3_rx_checks[] = {
      {.msg = {{0x370, 0, 8, 100U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x155, 1, 8, 50U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x20a, 1, 8, 50U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x368, 1, 8, 10U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x488, 2, 4, 50U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
    };
    tesla_legacy_chassis_bus = 1U;
    SET_RX_CHECKS(tesla_legacy_hw3_rx_checks, ret);
    SET_TX_MSGS(TESLA_LEGACY_TX_MSGS, ret);
  } else if (tesla_legacy_hw1) {
    static RxCheck tesla_legacy_hw1_rx_checks[] = {
      {.msg = {{0x108, 0, 8, 100U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x2b9, 2, 8, 25U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x370, 0, 8, 25U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x155, 0, 8, 50U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x20a, 0, 8, 50U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x368, 0, 8, 10U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x488, 2, 4, 50U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
    };
    tesla_legacy_di_torque1_addr = TESLA_LEGACY_ADDR_DI_TORQUE1_HW1;
    SET_RX_CHECKS(tesla_legacy_hw1_rx_checks, ret);
    SET_TX_MSGS(TESLA_LEGACY_HW1_TX_MSGS, ret);
  } else {
    static RxCheck tesla_legacy_hw2_rx_checks[] = {
      {.msg = {{0x370, 0, 8, 25U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x155, 0, 8, 50U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x20a, 0, 8, 50U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x368, 0, 8, 10U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
      {.msg = {{0x488, 2, 4, 50U, .ignore_quality_flag = true, .ignore_checksum = true, .ignore_counter = true}, { 0 }, { 0 }}},
    };
    SET_RX_CHECKS(tesla_legacy_hw2_rx_checks, ret);
    SET_TX_MSGS(TESLA_LEGACY_TX_MSGS, ret);
  }
  return ret;
}

const safety_hooks tesla_legacy_hooks = {
  .init = tesla_legacy_init,
  .rx = tesla_legacy_rx_hook,
  .tx = tesla_legacy_tx_hook,
  .fwd = tesla_legacy_fwd_hook,
};
