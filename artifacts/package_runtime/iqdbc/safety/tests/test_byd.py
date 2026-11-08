#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import unittest
import numpy as np

from iqdbc.car.byd.values import CarControllerParams, BydSafetyFlags
from iqdbc.car.byd.interface import CarInterface
from iqdbc.car.lateral import get_max_angle_delta_vm, get_max_angle_vm
from iqdbc.car.structs import CarParams
from iqdbc.car.vehicle_model import VehicleModel
from iqdbc.safety.tests.libsafety import libsafety_py
import iqdbc.safety.tests.common as common
from iqdbc.safety.tests.common import CANPackerSafety

STEERING_MODULE_ADAS = 0x1E2
LKAS_HUD_ADAS = 0x316
ACC_CMD = 0x32E
PCM_BUTTONS = 0x3B0

ACCEL_MIN = -3.5
ACCEL_MAX = 2.0


def safety_max_can(max_angle_float, can_offset=0):
  return int(max_angle_float * 10 + 1.) + can_offset


def get_safety_CP():
  return CarInterface.get_non_essential_params("BYD_SEALION_7")


class TestBydSafetyBase(common.CarSafetyTest, common.AngleSteeringSafetyTest):
  RELAY_MALFUNCTION_ADDRS = {0: (STEERING_MODULE_ADAS, LKAS_HUD_ADAS)}
  FWD_BLACKLISTED_ADDRS = {2: [STEERING_MODULE_ADAS, LKAS_HUD_ADAS]}
  TX_MSGS = [[STEERING_MODULE_ADAS, 0], [LKAS_HUD_ADAS, 0], [PCM_BUTTONS, 0]]

  MAIN_BUS = 0
  CAM_BUS = 2

  STEER_ANGLE_MAX = 390
  DEG_TO_CAN = 10

  ANGLE_RATE_BP = None
  ANGLE_RATE_UP = None
  ANGLE_RATE_DOWN = None

  LATERAL_FREQUENCY = 50

  SAFETY_PARAM = 0

  cnt_angle_cmd = 0

  def setUp(self):
    self.VM = VehicleModel(get_safety_CP())
    self.packer = CANPackerSafety("byd_sealion_7")
    self.safety = libsafety_py.libsafety
    self.safety.set_safety_hooks(CarParams.SafetyModel.byd, self.SAFETY_PARAM)
    self.safety.init_tests()

  def _get_steer_cmd_angle_max(self, speed):
    return get_max_angle_vm(max(speed, 1), self.VM, CarControllerParams)

  def _angle_cmd_msg(self, angle: float, enabled: bool, increment_timer: bool = True):
    values = {"STEER_ANGLE": angle, "STEER_REQ": 1 if enabled else 0, "STEER_REQ_ACTIVE_LOW": 0 if enabled else 1}
    if increment_timer:
      self.safety.set_timer(self.__class__.cnt_angle_cmd * int(1e6 / self.LATERAL_FREQUENCY))
      self.__class__.cnt_angle_cmd += 1
    return self.packer.make_can_msg_safety("STEERING_MODULE_ADAS", self.MAIN_BUS, values)

  def _angle_meas_msg(self, angle: float):
    values = {"STEER_ANGLE_2": angle}
    return self.packer.make_can_msg_safety("STEER_MODULE_2", self.MAIN_BUS, values)

  def _pcm_status_msg(self, enable):
    values = {"CRUISE_STATE": 2 if enable else 1}
    return self.packer.make_can_msg_safety("ACC_HUD_ADAS", self.MAIN_BUS, values)

  def test_cruise_state_not_read_from_constant_byte(self):
    self.safety.set_controls_allowed(0)
    for _ in range(5):
      self._rx(self.packer.make_can_msg_safety("ACC_HUD_ADAS", self.MAIN_BUS, {"CRUISE_STATE": 0}))
    self.assertFalse(self.safety.get_controls_allowed())
    for _ in range(5):
      self._rx(self.packer.make_can_msg_safety("ACC_HUD_ADAS", self.MAIN_BUS, {"CRUISE_STATE": 3}))
    self.assertTrue(self.safety.get_controls_allowed())

  def _speed_msg(self, speed):
    kph = speed * 3.6
    values = {"FL": kph, "FR": kph, "RL": kph, "RR": kph}
    return self.packer.make_can_msg_safety("WHEEL_SPEEDS", self.MAIN_BUS, values)

  def _user_brake_msg(self, brake):
    values = {"BRAKE_PRESSED": 1 if brake else 0}
    return self.packer.make_can_msg_safety("DRIVE_STATE", self.MAIN_BUS, values)

  def _user_gas_msg(self, gas):
    values = {"GAS_PEDAL": gas}
    return self.packer.make_can_msg_safety("PEDAL", self.MAIN_BUS, values)

  def test_angle_cmd_when_enabled(self):
    pass

  def test_gas_pedal_source(self):
    self._rx(self._user_gas_msg(0))
    self.assertFalse(self.safety.get_gas_pressed_prev())

    values = {"RAW_THROTTLE": 100}
    self._rx(self.packer.make_can_msg_safety("DRIVE_STATE", self.MAIN_BUS, values))
    self.assertFalse(self.safety.get_gas_pressed_prev())

    self._rx(self._user_gas_msg(1.0))
    self.assertTrue(self.safety.get_gas_pressed_prev())

  def test_wheel_speed_decode(self):
    for speed in (0.0, 5.0, 20.0, 40.0):
      self._reset_speed_measurement(speed)
      self.assertAlmostEqual(self.safety.get_vehicle_speed_min(), speed, delta=0.2)

  def test_lateral_accel_limit(self):
    for sent in np.linspace(1, 41, 100):
      for sign in (-1, 1):
        self.safety.set_controls_allowed(True)
        self._reset_speed_measurement(sent)
        speed = max(self.safety.get_vehicle_speed_min() - 1.0, 1.0)

        max_angle_float = get_max_angle_vm(speed, self.VM, CarControllerParams)

        max_angle_can = safety_max_can(max_angle_float)
        max_angle_can = min(max_angle_can, self.STEER_ANGLE_MAX * self.DEG_TO_CAN)
        max_angle = sign * max_angle_can / self.DEG_TO_CAN
        self.safety.set_desired_angle_last(sign * max_angle_can)

        self.assertTrue(self._tx(self._angle_cmd_msg(max_angle, True)))

        over_can = safety_max_can(max_angle_float, 1)
        over_can_clipped = min(over_can, self.STEER_ANGLE_MAX * self.DEG_TO_CAN)
        over_angle = sign * over_can_clipped / self.DEG_TO_CAN
        self._tx(self._angle_cmd_msg(over_angle, True))

        should_tx = over_can >= self.STEER_ANGLE_MAX * self.DEG_TO_CAN
        self.assertEqual(should_tx, self._tx(self._angle_cmd_msg(over_angle, True)))

  def test_lateral_jerk_limit(self):
    for sent in np.linspace(1, 41, 100):
      for sign in (-1, 1):
        self.safety.set_controls_allowed(True)
        self._reset_speed_measurement(sent)
        speed = max(self.safety.get_vehicle_speed_min() - 1.0, 1.0)
        self._tx(self._angle_cmd_msg(0, True))

        max_delta_float = get_max_angle_delta_vm(speed, self.VM, CarControllerParams)

        max_delta_can = safety_max_can(max_delta_float)
        max_angle_delta = sign * max_delta_can / self.DEG_TO_CAN
        self.assertTrue(self._tx(self._angle_cmd_msg(max_angle_delta, True)))
        self.assertTrue(self._tx(self._angle_cmd_msg(max_angle_delta, True)))
        self.assertTrue(self._tx(self._angle_cmd_msg(0, True)))

        over_delta_can = safety_max_can(max_delta_float, 1)
        max_angle_delta = sign * over_delta_can / self.DEG_TO_CAN
        self.assertFalse(self._tx(self._angle_cmd_msg(max_angle_delta, True)))

        self.safety.set_desired_angle_last(sign * over_delta_can)
        self.assertTrue(self._tx(self._angle_cmd_msg(max_angle_delta, True)))
        self.assertFalse(self._tx(self._angle_cmd_msg(0, True)))
        self.assertTrue(self._tx(self._angle_cmd_msg(0, True)))


class TestBydStockSafety(TestBydSafetyBase):
  def test_acc_cmd_blocked_without_long(self):
    self.safety.set_controls_allowed(True)
    values = {"ACCEL_CMD": 0.0}
    self.assertFalse(self._tx(self.packer.make_can_msg_safety("ACC_CMD", self.MAIN_BUS, values)))


class TestBydLongSafety(TestBydSafetyBase, common.LongitudinalAccelSafetyTest):
  TX_MSGS = [[STEERING_MODULE_ADAS, 0], [LKAS_HUD_ADAS, 0], [ACC_CMD, 0], [PCM_BUTTONS, 0]]
  RELAY_MALFUNCTION_ADDRS = {0: (STEERING_MODULE_ADAS, LKAS_HUD_ADAS, ACC_CMD)}
  FWD_BLACKLISTED_ADDRS = {2: [STEERING_MODULE_ADAS, LKAS_HUD_ADAS, ACC_CMD]}

  SAFETY_PARAM = BydSafetyFlags.LONG_CONTROL

  MAX_ACCEL = ACCEL_MAX
  MIN_ACCEL = ACCEL_MIN
  INACTIVE_ACCEL = 0.0

  def _accel_msg(self, accel):
    values = {"ACCEL_CMD": accel}
    return self.packer.make_can_msg_safety("ACC_CMD", self.MAIN_BUS, values)


if __name__ == "__main__":
  unittest.main()
