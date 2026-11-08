"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
OEM_ANGLE_RATE_LIMIT = 500
SET_ME_FF_VALUE = 0x64

# Must stay at the OEM value: lowering the pair to 300 stops the EPS steering entirely.
ANGLE_RATE_LIMIT_UPPER = OEM_ANGLE_RATE_LIMIT
ANGLE_RATE_LIMIT_LOWER = -OEM_ANGLE_RATE_LIMIT

LKAS_STATE_IDLE = 1
LKAS_STATE_SUSPENDED = 2
LKAS_STATE_ACTIVE = 3
LKAS_STATE_PREPARING = 5

GENERATED_SIGNALS = ("COUNTER", "CHECKSUM")


def byd_checksum(address: int, sig, d: bytearray) -> int:
  return (~sum(d[:7])) & 0xFF


def passthrough(stock: dict) -> dict:
  return {k: v for k, v in stock.items() if k not in GENERATED_SIGNALS}


def create_steering_control(packer, apply_angle: float, steer_req: bool):
  values = {
    "STEER_REQ": 1 if steer_req else 0,
    "STEER_REQ_ACTIVE_LOW": 0,
    "STEER_ANGLE": apply_angle,
    "ANGLE_RATE_LIMIT_UPPER": ANGLE_RATE_LIMIT_UPPER,
    "ANGLE_RATE_LIMIT_LOWER": ANGLE_RATE_LIMIT_LOWER,
    "E2E_ALIVE_1": 1,
    "E2E_ALIVE_2": 1,
    "SET_ME_FF": SET_ME_FF_VALUE,
    "SET_ME_F": 0xF,
  }
  return packer.make_can_msg("STEERING_MODULE_ADAS", 0, values)


def create_lkas_hud(packer, lkas_state: int, lkas_active: bool, stock_lkas_hud: dict, hud_control):
  values = passthrough(stock_lkas_hud)

  values["TJA_ICA_STATE"] = 0
  values["LKAS_STATE"] = lkas_state
  values["LKAS_ACTIVE"] = 1 if lkas_active else 0
  values["LKAS_REQ_PREPARE"] = 1 if lkas_state == LKAS_STATE_SUSPENDED else 0

  if lkas_state != LKAS_STATE_IDLE:
    values["LEFT_LANE_STATE"] = 1
    values["RIGHT_LANE_STATE"] = 1

  if hud_control is not None:
    if hud_control.leftLaneDepart:
      values["LEFT_LANE_STATE"] = 2
    if hud_control.rightLaneDepart:
      values["RIGHT_LANE_STATE"] = 2

  return packer.make_can_msg("LKAS_HUD_ADAS", 0, values)


def create_acc_cmd(packer, accel: float, long_active: bool, stock_acc_cmd: dict,
                   standstill: bool = False, resume: bool = False):
  holding = long_active and standstill and not resume

  if not long_active or abs(accel) < 0.1:
    accel_fac, decel_fac = 0, 0
  elif accel > 0:
    accel_fac, decel_fac = 12, 5
  elif accel > -1.5:
    accel_fac, decel_fac = 13, 1
  else:
    accel_fac, decel_fac = 1, 1

  values = {
    **passthrough(stock_acc_cmd),
    "ACCEL_CMD": accel if long_active else 0.0,
    "ACC_ON_1": 1 if long_active else 0,
    "ACC_ON_2": 1 if long_active else 0,
    "ACC_CONTROLLABLE_AND_ON": 1 if long_active else 0,
    "ACC_REQ_NOT_STANDSTILL": 0 if holding else (1 if long_active else 0),
    "CMD_REQ_ACTIVE_LOW": 0 if long_active else 1,
    "ACC_OVERRIDE_OR_STANDSTILL": 1 if holding else 0,
    "STANDSTILL_RESUME": 1 if (long_active and resume) else 0,
    "STANDSTILL_STATE": 1 if holding else 0,
    "ACCEL_FACTOR": accel_fac,
    "DECEL_FACTOR": decel_fac,
    "SET_ME_25_1": 25,
    "SET_ME_25_2": 25,
    "SET_ME_1": 1,
    "SET_ME_X8": 8,
    "SET_ME_XF": 15,
  }
  return packer.make_can_msg("ACC_CMD", 0, values)


def create_buttons(packer, stock_buttons: dict, cancel: bool):
  values = {
    **passthrough(stock_buttons),
    "SET_ME_1_1": 1,
    "SET_ME_1_2": 1,
    "ACC_ON_BTN": 1 if cancel else 0,
  }
  return packer.make_can_msg("PCM_BUTTONS", 0, values)
