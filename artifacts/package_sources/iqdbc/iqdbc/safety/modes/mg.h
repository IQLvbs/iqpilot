#pragma once

#include "iqdbc/safety/declarations.h"

static uint8_t mg_crc_lut[256];

static uint32_t mg_get_checksum(const CANPacket_t *msg) {
  uint32_t checksum = msg->data[7];
  if (msg->addr == 0x1ecU) {
    checksum = ((msg->data[2] & 0x7FU) << 8) | msg->data[3];
  }
  return checksum;
}

static uint32_t mg_compute_checksum(const CANPacket_t *msg) {
  uint32_t checksum;
  if (msg->addr == 0x1ecU) {
    uint32_t torque = ((msg->data[0] & 0x7U) << 8) | msg->data[1];
    uint32_t valid = (msg->data[0] >> 3) & 1U;
    uint32_t status = (msg->data[6] >> 4) & 0x7U;
    uint32_t counter = msg->data[0] >> 4;
    checksum = (0U - ((torque << 1) + (status << 12) + valid + counter)) & 0x7FFFU;
  } else {
    checksum = 0xFFU;
    for (int i = 0; i < 7; i++) {
      checksum ^= msg->data[i];
      checksum = mg_crc_lut[checksum];
    }
    checksum ^= 0xFFU;
  }
  return checksum;
}

static uint8_t mg_get_counter(const CANPacket_t *msg) {
  uint8_t counter = 0U;
  if (msg->addr == 0x23cU) {
    counter = (msg->data[4] >> 4) & 0xFU;
  }
  if (msg->addr == 0x1ecU) {
    counter = (msg->data[0] >> 4) & 0xFU;
  }
  if (msg->addr == 0x242U) {
    counter = (msg->data[0] >> 3) & 0xFU;
  }
  if (msg->addr == 0x1b6U) {
    counter = msg->data[6] & 0xFU;
  }
  if (msg->addr == 0xAFU) {
    counter = msg->data[5] >> 4U;
  }
  return counter;
}

static void mg_rx_hook(const CANPacket_t *msg) {
  if (msg->bus == 0U) {
    if (msg->addr == 0x23cU) {
      float speed = (((msg->data[2] & 0x7FU) << 8) | msg->data[3]) * 0.015625;
      vehicle_moving = speed > 0.0;
      UPDATE_VEHICLE_SPEED(speed * KPH_TO_MS);
    }

    if (msg->addr == 0xafU) {
      gas_pressed = msg->data[0] != 0U;
    }

    if (msg->addr == 0x1ecU) {
      int torque_driver_new = (int)(((msg->data[4] & 0x7U) << 8) | msg->data[5]) - 1024;
      update_sample(&torque_driver, torque_driver_new);
    }

    if (msg->addr == 0x1b6U) {
      brake_pressed = GET_BIT(msg, 10U);
    }

    if (msg->addr == 0x242U) {
      int cruise_state = (msg->data[5] & 0x38U) >> 3;
      bool cruise_engaged = (cruise_state == 2) || (cruise_state == 3);
      pcm_cruise_check(cruise_engaged);
    }
  }
}

static bool mg_tx_hook(const CANPacket_t *msg) {
  const TorqueSteeringLimits MG_STEERING_LIMITS = {
    .max_torque = 300,
    .max_rate_up = 6,
    .max_rate_down = 10,
    .max_rt_delta = 125,
    .driver_torque_multiplier = 2,
    .driver_torque_allowance = 100,
    .type = TorqueDriverLimited,
  };

  bool tx = true;

  if (msg->addr == 0x1fdU) {
    int desired_torque = (int)(((msg->data[0] & 0x7U) << 8) | msg->data[1]) - 1024;
    bool steer_req = GET_BIT(msg, 35U);

    if (steer_torque_cmd_checks(desired_torque, steer_req, MG_STEERING_LIMITS)) {
      tx = false;
    }
  }

  return tx;
}

static safety_config mg_init(uint16_t param) {
  SAFETY_UNUSED(param);

  gen_crc_lookup_table_8(0x1DU, mg_crc_lut);

  static const CanMsg MG_TX_MSGS[] = {{0x1fd, 0, 8, .check_relay = true}};

  static RxCheck mg_rx_checks[] = {
    {.msg = {{0x23c, 0, 8, .frequency = 50U,  .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{0xaf,  0, 8, .frequency = 100U, .ignore_checksum = true, .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{0x1ec, 0, 8, .frequency = 50U,  .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{0x242, 0, 8, .frequency = 50U,  .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
    {.msg = {{0x1b6, 0, 8, .frequency = 50U,  .max_counter = 15U, .ignore_quality_flag = true}, { 0 }, { 0 }}},
  };

  safety_config ret;
  SET_RX_CHECKS(mg_rx_checks, ret);
  SET_TX_MSGS(MG_TX_MSGS, ret);
  return ret;
}

const safety_hooks mg_hooks = {
  .init = mg_init,
  .rx = mg_rx_hook,
  .tx = mg_tx_hook,
  .get_checksum = mg_get_checksum,
  .compute_checksum = mg_compute_checksum,
  .get_counter = mg_get_counter,
};
