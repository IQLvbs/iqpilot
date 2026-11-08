"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import unittest

import numpy as np

from iqdbc.can.packer import CANPacker
from iqdbc.can.parser import CANParser
from iqdbc.car import structs
from iqdbc.car.byd import bydcan
from iqdbc.car.byd.carstate import EPS_STATE_OFF, EPS_STATE_PREPARED, EPS_STATE_ACTUATING, EPS_STATE_LATCHED_FAULT
from iqdbc.car.byd.fingerprints import FW_VERSIONS
from iqdbc.car.byd.interface import CarInterface
from iqdbc.car.byd.values import CAR, DBC, BydFlags, BydSafetyFlags, CarControllerParams
from iqdbc.car.fw_versions import match_fw_to_car_exact, build_fw_dict
from iqdbc.car.lateral import get_max_angle_delta_vm, get_max_angle_vm
from iqdbc.car.structs import CarParams

DBC_NAME = DBC[CAR.BYD_SEALION_7]['pt']
Ecu = CarParams.Ecu


def unpack(dbc_name, msg_name, dat):
  dbc = CANParser(dbc_name, [], 0).dbc
  msg = dbc.name_to_msg[msg_name]
  out = {}
  for sig in msg.sigs.values():
    val = 0
    if sig.is_little_endian:
      for i in range(sig.size):
        bit = sig.lsb + i
        val |= ((dat[bit // 8] >> (bit % 8)) & 1) << i
    else:
      be_bits = [j + i * 8 for i in range(64) for j in range(7, -1, -1)]
      idx = be_bits.index(sig.start_bit)
      for i in range(sig.size):
        bit = be_bits[idx + i]
        val = (val << 1) | ((dat[bit // 8] >> (bit % 8)) & 1)
    if sig.is_signed and (val & (1 << (sig.size - 1))):
      val -= (1 << sig.size)
    out[sig.name] = val * sig.factor + sig.offset
  return out


class TestBydChecksum(unittest.TestCase):
  def test_checksum_is_inverted_sum(self):
    for dat in (bytearray(8), bytearray(b'\x01' * 8), bytearray(b'\xff' * 8),
                bytearray(b'\x12\x34\x56\x78\x9a\xbc\xde\x00')):
      self.assertEqual(bydcan.byd_checksum(0, None, dat), (~sum(dat[:7])) & 0xFF)

  def test_packer_fills_checksum_and_counter(self):
    packer = CANPacker(DBC_NAME)
    seen = []
    for _ in range(18):
      _, dat, _ = packer.make_can_msg("STEERING_MODULE_ADAS", 0, {"STEER_REQ": 1})
      self.assertEqual(dat[7], (~sum(dat[:7])) & 0xFF)
      seen.append(dat[6] >> 4)
    self.assertEqual(seen[:16], list(range(16)))
    self.assertEqual(seen[16:], [0, 1])


class TestBydSteeringControl(unittest.TestCase):
  def setUp(self):
    self.packer = CANPacker(DBC_NAME)

  def test_steer_req_and_angle_round_trip(self):
    for angle in (-390.0, -100.5, 0.0, 12.3, 390.0):
      for lat_active in (True, False):
        _, dat, _ = bydcan.create_steering_control(self.packer, angle, lat_active)
        vals = unpack(DBC_NAME, "STEERING_MODULE_ADAS", dat)
        self.assertAlmostEqual(vals["STEER_ANGLE"], angle, places=4)
        self.assertEqual(vals["STEER_REQ"], 1 if lat_active else 0)
        self.assertEqual(vals["STEER_REQ_ACTIVE_LOW"], 0)
        self.assertEqual(vals["E2E_ALIVE_1"], 1)
        self.assertEqual(vals["E2E_ALIVE_2"], 1)

  def test_rate_limits_held_at_oem_value_regardless_of_request(self):
    for lat_active in (True, False):
      _, dat, _ = bydcan.create_steering_control(self.packer, 0.0, lat_active)
      vals = unpack(DBC_NAME, "STEERING_MODULE_ADAS", dat)
      self.assertEqual(vals["ANGLE_RATE_LIMIT_UPPER"], 500)
      self.assertEqual(vals["ANGLE_RATE_LIMIT_LOWER"], -500)

  def test_matches_stock_camera_idle_frame(self):
    _, dat, _ = bydcan.create_steering_control(self.packer, 0.0, False)
    self.assertEqual(bytes(dat[:3]), bytes.fromhex("f431c8"))
    self.assertEqual(dat[5], 0x64)

  def test_matches_stock_camera_engaged_frame(self):
    _, dat, _ = bydcan.create_steering_control(self.packer, 0.1, True)
    self.assertEqual(bytes(dat[:6]), bytes.fromhex("f431e8010064"))
    self.assertEqual(dat[6] & 0x0F, 0x0F)

  def test_authority_ceiling_is_oem_and_symmetric(self):
    self.assertEqual(bydcan.ANGLE_RATE_LIMIT_UPPER, bydcan.OEM_ANGLE_RATE_LIMIT)
    self.assertEqual(bydcan.ANGLE_RATE_LIMIT_LOWER, -bydcan.OEM_ANGLE_RATE_LIMIT)
    self.assertEqual(bydcan.SET_ME_FF_VALUE, 0x64)


class TestBydAngleEnvelope(unittest.TestCase):
  def test_command_clamp_is_below_eps_fault_angle(self):
    self.assertLessEqual(CarControllerParams.ANGLE_LIMITS.STEER_ANGLE_MAX, 90.)
    self.assertEqual(CarControllerParams.ANGLE_LIMITS.STEER_ANGLE_MAX, 85.)

  def test_handoff_hysteresis_sits_below_command_clamp(self):
    self.assertLess(CarControllerParams.MAX_STEER_ANGLE_RESUME, CarControllerParams.MAX_STEER_ANGLE)
    self.assertLess(CarControllerParams.MAX_STEER_ANGLE, CarControllerParams.ANGLE_LIMITS.STEER_ANGLE_MAX)

  def test_lateral_limits_come_from_lateral_module(self):
    from iqdbc.car.lateral import MAX_LATERAL_ACCEL, MAX_LATERAL_JERK
    self.assertEqual(CarControllerParams.ANGLE_LIMITS.MAX_LATERAL_ACCEL, MAX_LATERAL_ACCEL)
    self.assertEqual(CarControllerParams.ANGLE_LIMITS.MAX_LATERAL_JERK, MAX_LATERAL_JERK)

  def test_kommu_regime_is_one_set(self):
    self.assertAlmostEqual(CarControllerParams.STEER_LOWPASS_HZ, 2.0)
    self.assertAlmostEqual(CarControllerParams.MAX_ANGLE_ERROR, 10.0)
    self.assertGreaterEqual(CarControllerParams.ANGLE_LIMITS.MAX_ANGLE_RATE, 6.0)
    self.assertLess(CarInterface.get_non_essential_params("BYD_SEALION_7").steerActuatorDelay, 0.05)


class TestBydLowSpeedAngleRate(unittest.TestCase):
  def cap(self, limits, v):
    bp, vals = limits
    return float(np.interp(v, bp, vals))

  def test_crawl_taper_values(self):
    up = CarControllerParams.ANGLE_LIMITS.ANGLE_RATE_LIMIT_UP
    for v, expected in ((0.0, 0.3), (2.0, 1.0), (5.0, 1.5)):
      self.assertAlmostEqual(self.cap(up, v), expected)

  def test_standstill_slew_is_bounded(self):
    for limits in (CarControllerParams.ANGLE_LIMITS.ANGLE_RATE_LIMIT_UP, CarControllerParams.ANGLE_LIMITS.ANGLE_RATE_LIMIT_DOWN):
      self.assertLessEqual(self.cap(limits, 0.0), 0.5)

  def test_rate_cap_never_decreases_through_the_taper(self):
    for limits in (CarControllerParams.ANGLE_LIMITS.ANGLE_RATE_LIMIT_UP, CarControllerParams.ANGLE_LIMITS.ANGLE_RATE_LIMIT_DOWN):
      caps = [self.cap(limits, v) for v in np.linspace(0, 8, 50)]
      self.assertEqual(caps, sorted(caps))

  def test_down_rate_never_below_up_rate(self):
    for v in np.linspace(0, 40, 80):
      self.assertGreaterEqual(self.cap(CarControllerParams.ANGLE_LIMITS.ANGLE_RATE_LIMIT_DOWN, v),
                              self.cap(CarControllerParams.ANGLE_LIMITS.ANGLE_RATE_LIMIT_UP, v))

  def test_kommu_rates_at_speed(self):
    limits = CarControllerParams.ANGLE_LIMITS
    self.assertAlmostEqual(self.cap(limits.ANGLE_RATE_LIMIT_UP, 15.0), 3.0)
    self.assertAlmostEqual(self.cap(limits.ANGLE_RATE_LIMIT_DOWN, 15.0), 4.0)
    self.assertAlmostEqual(self.cap(limits.ANGLE_RATE_LIMIT_UP, 8.0), 3.7)
    self.assertAlmostEqual(self.cap(limits.ANGLE_RATE_LIMIT_DOWN, 8.0), 5.4)


class TestBydLkasHud(unittest.TestCase):
  def setUp(self):
    self.packer = CANPacker(DBC_NAME)
    self.stock = {
      "HMA_STATE": 3, "LEFT_LANE_STATE": 1, "LKS_MODE": 2, "HANDS_ON_WHEEL_REQ": 1,
      "TJA_ICA_STATE": 5, "HMA_ON_OFF": 1, "LKAS_OUTPUT": -20, "LKAS_REQ_PREPARE": 1,
      "LKAS_ACTIVE": 1, "SLA_STATE": 3, "RIGHT_LANE_STATE": 1, "LKAS_STATE": 0b1000,
      "SPEED_LIMIT_VALUE": 100, "LDSW_TYPE": 2, "COUNTER": 9, "CHECKSUM": 0x11,
    }

  def test_passes_stock_bits_through(self):
    _, dat, _ = bydcan.create_lkas_hud(self.packer, bydcan.LKAS_STATE_IDLE, False, self.stock, None)
    vals = unpack(DBC_NAME, "LKAS_HUD_ADAS", dat)
    for name in ("HMA_STATE", "LKS_MODE", "HANDS_ON_WHEEL_REQ", "HMA_ON_OFF", "LKAS_OUTPUT", "SLA_STATE",
                 "SPEED_LIMIT_VALUE", "LDSW_TYPE"):
      self.assertEqual(vals[name], self.stock[name], f"{name} was modified")

  def test_hands_on_wheel_req_never_cleared(self):
    for state, active in ((bydcan.LKAS_STATE_ACTIVE, True), (bydcan.LKAS_STATE_IDLE, False)):
      _, dat, _ = bydcan.create_lkas_hud(self.packer, state, active, self.stock, None)
      self.assertEqual(unpack(DBC_NAME, "LKAS_HUD_ADAS", dat)["HANDS_ON_WHEEL_REQ"], 1)

  def test_camera_error_state_never_forwarded(self):
    err_stock = dict(self.stock, TJA_ICA_STATE=2, LKAS_STATE=4)
    for state, active in ((bydcan.LKAS_STATE_ACTIVE, True), (bydcan.LKAS_STATE_PREPARING, False),
                          (bydcan.LKAS_STATE_IDLE, False)):
      _, dat, _ = bydcan.create_lkas_hud(self.packer, state, active, err_stock, None)
      vals = unpack(DBC_NAME, "LKAS_HUD_ADAS", dat)
      self.assertEqual(int(vals["TJA_ICA_STATE"]), 0)
      self.assertEqual(int(vals["LKAS_STATE"]), state)

  def test_matches_stock_camera_frames(self):
    stock = dict(self.stock, HMA_STATE=15, LKS_MODE=3, HANDS_ON_WHEEL_REQ=1, HMA_ON_OFF=1,
                 LKAS_OUTPUT=0, SLA_STATE=7, SPEED_LIMIT_VALUE=1270, LDSW_TYPE=1, SET_ME_3=3)
    for state, active, oem in (
        (bydcan.LKAS_STATE_ACTIVE, True, "df8400f037ff"),
        (bydcan.LKAS_STATE_PREPARING, False, "df8400e057ff"),
        (bydcan.LKAS_STATE_SUSPENDED, False, "df8400e827ff"),
    ):
      _, dat, _ = bydcan.create_lkas_hud(self.packer, state, active, stock, None)
      self.assertEqual(bytes(dat[:6]), bytes.fromhex(oem), f"state {state}")
    self.assertEqual(dat[6] & 0x0F, 0x01)

  def test_prepare_bit_accompanies_exactly_the_suspend_state(self):
    for state, active, expected in ((bydcan.LKAS_STATE_IDLE, False, 0),
                                    (bydcan.LKAS_STATE_PREPARING, False, 0),
                                    (bydcan.LKAS_STATE_ACTIVE, True, 0),
                                    (bydcan.LKAS_STATE_SUSPENDED, False, 1)):
      _, dat, _ = bydcan.create_lkas_hud(self.packer, state, active, self.stock, None)
      self.assertEqual(int(unpack(DBC_NAME, "LKAS_HUD_ADAS", dat)["LKAS_REQ_PREPARE"]), expected)

  def test_lane_bits_lit_in_every_non_idle_state(self):
    stock = dict(self.stock, LEFT_LANE_STATE=0, RIGHT_LANE_STATE=0)
    for state, active in ((bydcan.LKAS_STATE_PREPARING, False), (bydcan.LKAS_STATE_ACTIVE, True),
                          (bydcan.LKAS_STATE_SUSPENDED, False)):
      _, dat, _ = bydcan.create_lkas_hud(self.packer, state, active, stock, None)
      vals = unpack(DBC_NAME, "LKAS_HUD_ADAS", dat)
      self.assertEqual(int(vals["LEFT_LANE_STATE"]), 1)
      self.assertEqual(int(vals["RIGHT_LANE_STATE"]), 1)

  def test_counter_not_inherited_from_stock(self):
    counters = []
    for _ in range(4):
      _, dat, _ = bydcan.create_lkas_hud(self.packer, bydcan.LKAS_STATE_ACTIVE, True, self.stock, None)
      counters.append(int(unpack(DBC_NAME, "LKAS_HUD_ADAS", dat)["COUNTER"]))
    self.assertNotEqual(counters, [self.stock["COUNTER"]] * 4)
    self.assertEqual(counters, [(counters[0] + i) % 16 for i in range(4)])

  def test_checksum_recomputed_not_inherited(self):
    _, dat, _ = bydcan.create_lkas_hud(self.packer, bydcan.LKAS_STATE_ACTIVE, True, self.stock, None)
    self.assertEqual(dat[7], (~sum(dat[:7])) & 0xFF)


class TestBydAccCmd(unittest.TestCase):
  def setUp(self):
    self.packer = CANPacker(DBC_NAME)
    self.stock = {"ACCEL_CMD": 0.0, "COUNTER": 7, "CHECKSUM": 0x22}

  def test_accel_scale_is_physical(self):
    for accel in (-3.0, -1.5, 0.0, 0.5, 1.5):
      _, dat, _ = bydcan.create_acc_cmd(self.packer, accel, True, self.stock)
      self.assertEqual(dat[0], round((accel + 5.0) / 0.05))
      self.assertAlmostEqual(unpack(DBC_NAME, "ACC_CMD", dat)["ACCEL_CMD"], accel, places=6)

  def test_inactive_commands_zero_accel(self):
    _, dat, _ = bydcan.create_acc_cmd(self.packer, -2.0, False, self.stock)
    vals = unpack(DBC_NAME, "ACC_CMD", dat)
    self.assertEqual(vals["ACCEL_CMD"], 0.0)
    self.assertEqual(dat[0], 100)
    self.assertEqual(vals["ACC_ON_1"], 0)
    self.assertEqual(vals["ACC_ON_2"], 0)
    self.assertEqual(vals["ACC_CONTROLLABLE_AND_ON"], 0)
    self.assertEqual(vals["CMD_REQ_ACTIVE_LOW"], 1)

  def test_standstill_hold_and_resume(self):
    _, dat, _ = bydcan.create_acc_cmd(self.packer, -0.5, True, self.stock, standstill=True)
    vals = unpack(DBC_NAME, "ACC_CMD", dat)
    self.assertEqual(vals["STANDSTILL_STATE"], 1)
    self.assertEqual(vals["ACC_OVERRIDE_OR_STANDSTILL"], 1)
    self.assertEqual(vals["ACC_REQ_NOT_STANDSTILL"], 0)
    self.assertEqual(vals["STANDSTILL_RESUME"], 0)

    _, dat, _ = bydcan.create_acc_cmd(self.packer, 0.5, True, self.stock, standstill=True, resume=True)
    vals = unpack(DBC_NAME, "ACC_CMD", dat)
    self.assertEqual(vals["STANDSTILL_RESUME"], 1)
    self.assertEqual(vals["STANDSTILL_STATE"], 0)
    self.assertEqual(vals["ACC_REQ_NOT_STANDSTILL"], 1)

  def test_regime_pairs(self):
    for accel, expected in ((0.0, (0, 0)), (0.05, (0, 0)), (0.8, (12, 5)), (-1.0, (13, 1)), (-2.5, (1, 1))):
      _, dat, _ = bydcan.create_acc_cmd(self.packer, accel, True, self.stock)
      vals = unpack(DBC_NAME, "ACC_CMD", dat)
      self.assertEqual((int(vals["ACCEL_FACTOR"]), int(vals["DECEL_FACTOR"])), expected, f"{accel=}")

  def test_accel_within_safety_bounds(self):
    self.assertGreaterEqual(CarControllerParams.ACCEL_MIN, -3.5)
    self.assertLessEqual(CarControllerParams.ACCEL_MAX, 2.0)


class TestBydEpsState(unittest.TestCase):
  def test_state_nibble_table(self):
    for prepared, activated, expected in ((0, 0, EPS_STATE_OFF), (1, 0, EPS_STATE_PREPARED),
                                          (0, 1, EPS_STATE_ACTUATING), (1, 1, EPS_STATE_LATCHED_FAULT)):
      self.assertEqual(EPS_STATE_OFF + prepared + 2 * activated, expected)

  def test_steering_torque_layout(self):
    sigs = CANParser(DBC_NAME, [], 0).dbc.name_to_msg["STEERING_TORQUE"].sigs
    for name, start, size in (("LKS_PREPARED", 0, 1), ("CRUISE_ACTIVATED", 1, 1), ("TORQUE_FAILED", 2, 1),
                              ("DRIVER_TORQUE", 4, 12), ("TARGET_ANGLE", 16, 16), ("MAIN_TORQUE", 32, 12)):
      self.assertEqual((sigs[name].start_bit, sigs[name].size), (start, size), name)
    self.assertTrue(sigs["DRIVER_TORQUE"].is_signed)
    self.assertTrue(sigs["MAIN_TORQUE"].is_signed)

  def test_driver_torque_decodes_negative(self):
    packer = CANPacker(DBC_NAME)
    for torque in (-20.0, -0.5, 0.0, 0.5, 20.0):
      _, dat, _ = packer.make_can_msg("STEERING_TORQUE", 0, {"DRIVER_TORQUE": torque})
      self.assertAlmostEqual(unpack(DBC_NAME, "STEERING_TORQUE", dat)["DRIVER_TORQUE"], torque, places=4)


class TestBydCruiseState(unittest.TestCase):
  def test_cruise_state_is_the_byte5_high_nibble(self):
    sig = CANParser(DBC_NAME, [], 0).dbc.name_to_msg["ACC_HUD_ADAS"].sigs["CRUISE_STATE"]
    self.assertEqual((sig.start_bit, sig.size), (44, 4))
    self.assertNotIn("ACC_STATE", CANParser(DBC_NAME, [], 0).dbc.name_to_msg["ACC_HUD_ADAS"].sigs)

  def test_accessories_on_bus_zero(self):
    parsers = CarInterface.CarState.get_can_parsers(CarInterface.get_non_essential_params("BYD_SEALION_7"), None)
    self.assertEqual(parsers["pt"].bus, 0)
    self.assertEqual(parsers["cam"].bus, 2)


class TestBydButtons(unittest.TestCase):
  def test_button_bits(self):
    sigs = CANParser(DBC_NAME, [], 0).dbc.name_to_msg["PCM_BUTTONS"].sigs
    self.assertEqual(sigs["SET_BTN"].start_bit, 3)
    self.assertEqual(sigs["RES_BTN"].start_bit, 4)
    self.assertEqual(sigs["LKAS_ON_BTN"].start_bit, 6)

  def test_checksum_covers_first_seven_bytes(self):
    _, dat, _ = CANPacker(DBC_NAME).make_can_msg("PCM_BUTTONS", 0, {"SET_BTN": 1})
    self.assertEqual(dat[7], (~sum(dat[:7])) & 0xFF)


class TestBydWheelSpeeds(unittest.TestCase):
  def test_four_independent_wheels(self):
    sigs = CANParser(DBC_NAME, [], 0).dbc.name_to_msg["WHEEL_SPEEDS"].sigs
    for name, start in (("FL", 0), ("FR", 16), ("RL", 28), ("RR", 40)):
      self.assertEqual(sigs[name].start_bit, start)
      self.assertEqual(sigs[name].size, 12)
      self.assertAlmostEqual(sigs[name].factor, 0.0725)

  def test_wheel_speeds_round_trip(self):
    _, dat, _ = CANPacker(DBC_NAME).make_can_msg("WHEEL_SPEEDS", 0, {"FL": 50.0, "FR": 51.0, "RL": 52.0, "RR": 53.0})
    vals = unpack(DBC_NAME, "WHEEL_SPEEDS", dat)
    for name, expected in (("FL", 50.0), ("FR", 51.0), ("RL", 52.0), ("RR", 53.0)):
      self.assertAlmostEqual(vals[name], expected, delta=0.0725)


class TestBydFingerprint(unittest.TestCase):
  def test_placeholder_never_matches_a_real_car(self):
    self.assertTrue(FW_VERSIONS[CAR.BYD_SEALION_7])
    live = build_fw_dict([CarParams.CarFw(ecu=Ecu.engine, fwVersion=b'REAL_CAR_FW', brand='byd',
                                          address=0x7e0, subAddress=0)])
    self.assertNotIn(str(CAR.BYD_SEALION_7), match_fw_to_car_exact(live, 'byd'))

  def test_fuzzy_match_requires_vds(self):
    from iqdbc.car.byd.values import match_fw_to_car_fuzzy
    self.assertEqual(CAR.BYD_SEALION_7.config.vds_prefixes, set())
    vin = "LGX" + "A" * 6 + "R" + "A" * 7
    self.assertEqual(match_fw_to_car_fuzzy({}, vin, {}), set())


class ControllerHarness:
  def __init__(self):
    self.CP = CarInterface.get_non_essential_params("BYD_SEALION_7")
    self.CP_IQ = CarInterface.get_non_essential_params_iq(self.CP, "BYD_SEALION_7")
    self.controller = CarInterface.CarController({'pt': DBC_NAME}, self.CP, self.CP_IQ)
    self.carstate = CarInterface.CarState(self.CP, self.CP_IQ)

  def step(self, lat_active, eps_state=EPS_STATE_ACTUATING, measured=0.0, desired=0.0, v_ego=20.0,
           long_active=False, frame_time=0):
    CC_obj = structs.CarControl()
    CC_obj.enabled = lat_active
    CC_obj.latActive = lat_active
    CC_obj.longActive = long_active
    CC_obj.actuators.steeringAngleDeg = desired
    CC = CC_obj.as_reader()

    cs_out = structs.CarState()
    cs_out.steeringAngleDeg = measured
    cs_out.vEgoRaw = v_ego
    cs_out.vEgo = v_ego

    class FakeCS:
      pass
    cs = FakeCS()
    cs.out = cs_out
    cs.eps_state = eps_state
    cs.lkas_hud = self.carstate.lkas_hud
    cs.acc_cmd = self.carstate.acc_cmd
    cs.buttons = self.carstate.buttons
    return self.controller.update(CC, structs.IQCarControl(), cs, frame_time)

  def steering_frames(self, **kwargs):
    _, can_sends = self.step(**kwargs)
    return [unpack(DBC_NAME, "STEERING_MODULE_ADAS", dat) for addr, dat, _ in can_sends if addr == 0x1E2]

  def command(self, **kwargs):
    if self.controller.frame % 2:
      self.step(**kwargs)
    vals = self.steering_frames(**kwargs)[0]
    self.step(**kwargs)
    return vals

  def run_frames(self, count, **kwargs):
    sent = []
    for i in range(count):
      _, can_sends = self.step(frame_time=i * 10_000_000, **kwargs)
      sent.append([addr for addr, _, _ in can_sends])
    return sent


class TestBydCarController(unittest.TestCase):
  def test_steering_stream_is_continuous_when_inactive(self):
    for lat_active in (True, False):
      sent = ControllerHarness().run_frames(20, lat_active=lat_active)
      self.assertEqual([i for i, a in enumerate(sent) if 0x1E2 in a], list(range(0, 20, 2)), f"{lat_active=}")
      self.assertEqual([i for i, a in enumerate(sent) if 0x316 in a], list(range(0, 20, 2)), f"{lat_active=}")

  def test_req_follows_lat_active(self):
    for lat_active in (True, False):
      frames = ControllerHarness().steering_frames(lat_active=lat_active)
      self.assertTrue(frames)
      for vals in frames:
        self.assertEqual(int(vals["STEER_REQ"]), 1 if lat_active else 0)

  def test_latched_fault_drops_req(self):
    frames = ControllerHarness().steering_frames(lat_active=True, eps_state=EPS_STATE_LATCHED_FAULT)
    self.assertTrue(frames)
    for vals in frames:
      self.assertEqual(int(vals["STEER_REQ"]), 0)

  def test_no_acc_cmd_without_openpilot_longitudinal(self):
    sent = ControllerHarness().run_frames(20, lat_active=True, long_active=True)
    self.assertFalse(any(0x32E in addrs for addrs in sent))

  def test_command_tracks_wheel_when_inactive(self):
    frames = ControllerHarness().steering_frames(lat_active=False, measured=12.3, desired=40.0)
    self.assertAlmostEqual(frames[0]["STEER_ANGLE"], 12.3, places=1)

  def test_handoff_drops_req_above_limit_and_resumes_below_resume_angle(self):
    harness = ControllerHarness()
    for measured, expected in ((70.0, 1), (81.0, 0), (70.0, 0), (66.0, 0), (64.0, 1)):
      self.assertEqual(int(harness.command(lat_active=True, measured=measured)["STEER_REQ"]), expected, f"{measured=}")

  def test_command_never_exceeds_clamp(self):
    harness = ControllerHarness()
    for i in range(400):
      vals = harness.command(lat_active=True, measured=min(i * 0.5, 79.0), desired=300.0, v_ego=3.0)
      self.assertLessEqual(abs(vals["STEER_ANGLE"]), CarControllerParams.ANGLE_LIMITS.STEER_ANGLE_MAX + 0.1)

  def test_command_stays_inside_safety_envelope(self):
    VM = ControllerHarness().controller.VM
    for v in (2.0, 5.0, 10.0, 20.0, 35.0):
      harness = ControllerHarness()
      last = 0.0
      for i in range(120):
        cmd = harness.command(lat_active=True, measured=last, desired=60.0 if i < 60 else -60.0, v_ego=v)["STEER_ANGLE"]
        max_delta = get_max_angle_delta_vm(max(v - 1.0, 1.0), VM, CarControllerParams)
        self.assertLessEqual(abs(cmd - last), max_delta + 0.11, f"{v=} step {i}")
        self.assertLessEqual(abs(cmd), get_max_angle_vm(max(v - 1.0, 1.0), VM, CarControllerParams) + 0.11, f"{v=} step {i}")
        last = cmd

  def test_crawl_slew_is_bounded(self):
    harness = ControllerHarness()
    last = 0.0
    for _ in range(50):
      cmd = harness.command(lat_active=True, measured=0.0, desired=60.0, v_ego=0.0)["STEER_ANGLE"]
      self.assertLessEqual(abs(cmd - last), 0.3 + 0.11)
      last = cmd


class TestBydHarnessType(unittest.TestCase):
  @staticmethod
  def params(cam_bus_addrs, alpha_long=True):
    fp = {0: {0x1FC: 8, 0x1F0: 8}, 1: {}, 2: dict.fromkeys(cam_bus_addrs, 8)}
    return CarInterface.get_params("BYD_SEALION_7", fp, [], alpha_long, False, False)

  def test_defaults_to_camera_harness_lateral_only(self):
    CP = self.params([0x1E2, 0x316])
    self.assertFalse(CP.flags & BydFlags.GATEWAY_HARNESS)
    self.assertFalse(CP.alphaLongitudinalAvailable)
    self.assertFalse(CP.openpilotLongitudinalControl)
    self.assertFalse(CP.safetyConfigs[0].safetyParam & BydSafetyFlags.LONG_CONTROL)

  def test_acc_cmd_on_fingerprint_bus2_does_not_imply_gateway(self):
    CP = self.params([0x1E2, 0x316, 0x32E, 0x32D, 0x1FC])
    self.assertFalse(CP.flags & BydFlags.GATEWAY_HARNESS)
    self.assertFalse(CP.alphaLongitudinalAvailable)
    self.assertFalse(CP.openpilotLongitudinalControl)

  def test_lateral_still_available_on_camera_harness(self):
    CP = self.params([0x1E2, 0x316])
    self.assertFalse(CP.dashcamOnly)
    self.assertEqual(CP.steerControlType, CarParams.SteerControlType.angle)


class TestBydCarParams(unittest.TestCase):
  def test_angle_control_and_no_radar(self):
    CP = CarInterface.get_non_essential_params("BYD_SEALION_7")
    self.assertEqual(CP.brand, "byd")
    self.assertEqual(CP.steerControlType, CarParams.SteerControlType.angle)
    self.assertEqual(CP.safetyConfigs[0].safetyModel, CarParams.SafetyModel.byd)
    self.assertTrue(CP.radarUnavailable)
    self.assertFalse(CP.dashcamOnly)

  def test_steer_step_matches_safety_frequency(self):
    self.assertEqual(CarControllerParams.STEER_STEP, 2)


if __name__ == "__main__":
  unittest.main()
