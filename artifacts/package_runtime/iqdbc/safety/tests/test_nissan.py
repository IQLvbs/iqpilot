#!/usr/bin/env python3
import unittest

from iqdbc.car.nissan.values import CAR, NissanSafetyFlags
from iqdbc.car.structs import CarParams

# NISSAN_PARAM_IQ_LEAF in safety/modes/nissan.h (IQ safety framework flag)
NISSAN_PARAM_IQ_LEAF = 1
from iqdbc.safety.tests.libsafety import libsafety_py
import iqdbc.safety.tests.common as common
from iqdbc.safety.tests.common import CANPackerSafety


class TestNissanSafety(common.CarSafetyTest, common.AngleSteeringSafetyTest):

  TX_MSGS = [[0x169, 0], [0x2b1, 0], [0x4cc, 0], [0x20b, 2], [0x280, 2]]
  GAS_PRESSED_THRESHOLD = 3
  RELAY_MALFUNCTION_ADDRS = {0: (0x169, 0x2b1, 0x4cc), 2: (0x280,)}
  FWD_BLACKLISTED_ADDRS = {0: [0x280], 2: [0x169, 0x2b1, 0x4cc]}

  EPS_BUS = 0
  CRUISE_BUS = 2
  ACC_MAIN_BUS = 1
  FILTER_PLATFORM = CAR.NISSAN_XTRAIL

  # Angle control limits
  STEER_ANGLE_MAX = 600  # deg, reasonable limit
  DEG_TO_CAN = 100

  ANGLE_RATE_BP = [0., 5., 15.]
  ANGLE_RATE_UP = [5., .8, .15]  # windup limit
  ANGLE_RATE_DOWN = [5., 3.5, .4]  # unwind limit

  def setUp(self):
    self.packer = CANPackerSafety("nissan_x_trail_2017_generated")
    self.safety = libsafety_py.libsafety
    self.safety.set_safety_hooks(CarParams.SafetyModel.nissan, 0)
    self.safety.init_tests()

  def _angle_cmd_msg(self, angle: float, enabled: bool):
    values = {"DESIRED_ANGLE": angle, "LKA_ACTIVE": 1 if enabled else 0}
    return self.packer.make_can_msg_safety("LKAS", 0, values)

  def _angle_meas_msg(self, angle: float):
    values = {"STEER_ANGLE": angle}
    return self.packer.make_can_msg_safety("STEER_ANGLE_SENSOR", self.EPS_BUS, values)

  def _pcm_status_msg(self, enable):
    values = {"CRUISE_ENABLED": enable}
    return self.packer.make_can_msg_safety("CRUISE_STATE", self.CRUISE_BUS, values)

  def _speed_msg(self, speed):
    values = {"WHEEL_SPEED_%s" % s: speed * 3.6 for s in ["RR", "RL"]}
    return self.packer.make_can_msg_safety("WHEEL_SPEEDS_REAR", self.EPS_BUS, values)

  def _user_brake_msg(self, brake):
    values = {"USER_BRAKE_PRESSED": brake}
    return self.packer.make_can_msg_safety("DOORS_LIGHTS", self.EPS_BUS, values)

  def _user_gas_msg(self, gas):
    values = {"GAS_PEDAL": gas}
    return self.packer.make_can_msg_safety("GAS_PEDAL", self.EPS_BUS, values)

  def _acc_state_msg(self, main_on):
    values = {"CRUISE_ON": main_on}
    return self.packer.make_can_msg_safety("PRO_PILOT", self.ACC_MAIN_BUS, values)

  def _acc_button_cmd(self, cancel=0, propilot=0, flw_dist=0, _set=0, res=0):
    no_button = not any([cancel, propilot, flw_dist, _set, res])
    values = {"CANCEL_BUTTON": cancel, "PROPILOT_BUTTON": propilot,
              "FOLLOW_DISTANCE_BUTTON": flw_dist, "SET_BUTTON": _set,
              "RES_BUTTON": res, "NO_BUTTON_PRESSED": no_button}
    return self.packer.make_can_msg_safety("CRUISE_THROTTLE", 2, values)

  def test_acc_buttons(self):
    btns = [
      ("cancel", True),
      ("propilot", False),
      ("flw_dist", False),
      ("_set", False),
      ("res", False),
      (None, False),
    ]
    for controls_allowed in (True, False):
      for btn, should_tx in btns:
        self.safety.set_controls_allowed(controls_allowed)
        args = {} if btn is None else {btn: 1}
        tx = self._tx(self._acc_button_cmd(**args))
        self.assertEqual(tx, should_tx)


class TestNissanSafetyAltEpsBus(TestNissanSafety):
  """Altima uses different buses"""

  EPS_BUS = 1
  CRUISE_BUS = 1
  ACC_MAIN_BUS = 2
  FILTER_PLATFORM = CAR.NISSAN_ALTIMA

  def setUp(self):
    self.packer = CANPackerSafety("nissan_x_trail_2017_generated")
    self.safety = libsafety_py.libsafety
    self.safety.set_safety_hooks(CarParams.SafetyModel.nissan, NissanSafetyFlags.ALT_EPS_BUS)
    self.safety.init_tests()


class TestNissanLeafSafety(TestNissanSafety):
  FILTER_PLATFORM = CAR.NISSAN_LEAF

  def setUp(self):
    self.packer = CANPackerSafety("nissan_leaf_2018_generated")
    self.safety = libsafety_py.libsafety
    self.safety.set_current_safety_param_iq(NISSAN_PARAM_IQ_LEAF)
    self.safety.set_safety_hooks(CarParams.SafetyModel.nissan, 0)
    self.safety.init_tests()

  def _user_brake_msg(self, brake):
    values = {"USER_BRAKE_PRESSED": brake}
    return self.packer.make_can_msg_safety("CRUISE_THROTTLE", 0, values)

  def _user_gas_msg(self, gas):
    values = {"GAS_PEDAL": gas}
    return self.packer.make_can_msg_safety("CRUISE_THROTTLE", 0, values)

  def _acc_state_msg(self, main_on):
    values = {"CRUISE_AVAILABLE": main_on}
    return self.packer.make_can_msg_safety("CRUISE_THROTTLE", 0, values)

  # TODO: leaf should use its own safety param
  def test_acc_buttons(self):
    pass

  def test_controller_commands_through_the_low_speed_angle_filter_are_accepted(self):
    import math
    from iqdbc.car.nissan.tests.test_nissan import drive, ready_interface

    for platform in (self.FILTER_PLATFORM,):
      ci = ready_interface(platform)
      for v_ego in (0.5, 2.0, 5.0, 8.0, 12.0, 18.0, 25.0, 35.0):
        self.safety.init_tests()
        self.safety.set_controls_allowed(True)
        self._rx(self._speed_msg(v_ego))
        measured = 0.0
        for frame in range(400):
          command = 70.0 * math.sin(2 * math.pi * frame / 150) + (45.0 if (frame // 100) % 2 else -45.0)
          ci.CS.out.steeringAngleDeg = measured
          cc = drive(ci, v_ego, command)
          applied = cc.apply_angle_last
          self.assertTrue(self._tx(self._angle_cmd_msg(applied, True)), (platform, v_ego, frame, command, applied, measured))
          measured = applied
          self._rx(self._angle_meas_msg(measured))


if __name__ == "__main__":
  unittest.main()
