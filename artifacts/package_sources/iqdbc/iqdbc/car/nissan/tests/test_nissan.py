"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import pytest

from iqdbc.can import CANPacker, CANParser
from iqdbc.car import Bus, structs
from iqdbc.car.nissan.interface import CarInterface
from iqdbc.car.nissan.values import CAR, DBC

GearShifter = structs.CarState.GearShifter
LKAS_ADDR = 361
LKAS_STATUS_INACTIVE = 5
LKAS_STATUS_ACTIVE = 6
LKAS_STATUS_FAULT = 9

ALL_PLATFORMS = list(CAR)
LOW_GEAR_PLATFORMS = [CAR.NISSAN_XTRAIL, CAR.NISSAN_ROGUE, CAR.NISSAN_ALTIMA]


def make_interface(platform):
  fingerprint = {0: {}}
  CP = CarInterface.get_params(platform, fingerprint, [], False, False, False)
  CP_IQ = CarInterface.get_params_iq(CP, platform, fingerprint, [], False, False, False)
  return CarInterface(CP, CP_IQ)


def settle(ci, frames):
  ci.update(frames)
  return ci.update(frames)


def pt_bus(platform):
  return 1 if platform == CAR.NISSAN_ALTIMA else 0


def idle_frames(platform, overrides=None):
  overrides = overrides or {}
  packer = CANPacker(DBC[platform][Bus.pt])
  frames = []
  for msg in packer.dbc.msgs.values():
    for bus in (0, 1, 2):
      frames.append(packer.make_can_msg(msg.name, bus, overrides.get((msg.name, bus), {})))
  return [(0, frames)]


def decode_lkas_max_torque(platform, can_sends):
  parser = CANParser(DBC[platform][Bus.pt], [("LKAS", 50)], 0)
  parser.update([(0, [send for send in can_sends if send[0] == LKAS_ADDR])])
  return parser.vl["LKAS"]["MAX_TORQUE"]


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
@pytest.mark.parametrize("status,fault", [
  (LKAS_STATUS_INACTIVE, False),
  (LKAS_STATUS_ACTIVE, False),
  (LKAS_STATUS_FAULT, True),
])
def test_eps_fault_status(platform, status, fault):
  ci = make_interface(platform)
  frames = idle_frames(platform, {("STEER_TORQUE_SENSOR", 0): {"LKAS_STATUS": status}})
  CS, _ = settle(ci, frames)
  assert CS.steerFaultTemporary == fault
  assert not CS.steerFaultPermanent


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
def test_idle_state_reports_no_steer_fault(platform):
  ci = make_interface(platform)
  CS, _ = settle(ci, idle_frames(platform))
  assert not CS.steerFaultTemporary


@pytest.mark.parametrize("platform", LOW_GEAR_PLATFORMS)
def test_low_gear_is_drivable(platform):
  ci = make_interface(platform)
  frames = idle_frames(platform, {("GEARBOX", pt_bus(platform)): {"GEAR_SHIFTER": 6}})
  CS, _ = settle(ci, frames)
  assert CS.gearShifter == GearShifter.low
  assert CS.gearShifter in ci.DRIVABLE_GEARS


@pytest.mark.parametrize("platform", [CAR.NISSAN_LEAF, CAR.NISSAN_LEAF_IC])
def test_leaf_brake_gear_still_drivable(platform):
  ci = make_interface(platform)
  frames = idle_frames(platform, {("GEARBOX", 0): {"GEAR_SHIFTER": 7}})
  CS, _ = settle(ci, frames)
  assert CS.gearShifter == GearShifter.brake
  assert CS.gearShifter in ci.DRIVABLE_GEARS


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
@pytest.mark.parametrize("driver_torque,pressed,expected", [
  (0.0, False, 1.0),
  (5.0, False, 1.0),
  (0.5, True, 1.0),
  (1.0, True, 1.0),
  (2.0, True, 0.4),
  (3.0, True, 0.2),
  (5.0, True, 0.2),
  (-5.0, True, 0.2),
])
def test_lkas_max_torque_winds_down_under_driver_override(platform, driver_torque, pressed, expected):
  ci = make_interface(platform)
  settle(ci, idle_frames(platform))
  ci.CS.out.steeringPressed = pressed
  ci.CS.out.steeringTorque = driver_torque
  CC = structs.CarControl()
  CC.latActive = True
  _, can_sends = ci.apply(CC.as_reader(), structs.IQCarControl(), 0)
  assert decode_lkas_max_torque(platform, can_sends) == pytest.approx(expected, abs=0.005)


def ready_interface(platform):
  ci = make_interface(platform)
  settle(ci, idle_frames(platform))
  return ci


def drive(ci, v_ego, command, active=True):
  ci.CS.out.vEgo = v_ego
  ci.CS.out.vEgoRaw = v_ego
  control = structs.CarControl.new_message()
  control.enabled = active
  control.latActive = active
  control.actuators.steeringAngleDeg = command
  ci.apply(control.as_reader(), structs.IQCarControl())
  return ci.CC


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
@pytest.mark.parametrize("v_ego,rc", [(2.0, 0.2), (5.0, 0.2), (7.5, 0.15), (10.0, 0.1), (15.0, 0.05)])
def test_angle_filter_time_constant_follows_speed(platform, v_ego, rc):
  ci = ready_interface(platform)
  drive(ci, v_ego, 0.0, active=False)
  cc = drive(ci, v_ego, 20.0)
  dt = 0.01
  assert cc.angle_filter.x == pytest.approx(20.0 * dt / (rc + dt), rel=1e-6)


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
@pytest.mark.parametrize("v_ego", (20.0, 25.0, 40.0))
def test_angle_filter_is_transparent_from_twenty_meters_per_second(platform, v_ego):
  from iqdbc.car.lateral import apply_std_steer_angle_limits
  from iqdbc.car.nissan.values import CarControllerParams

  ci = ready_interface(platform)
  reference = 0
  for frame in range(200):
    command = 12.0 * ((frame % 40) - 20) / 20.0 + 3.0
    cc = drive(ci, v_ego, command)
    reference = apply_std_steer_angle_limits(command, reference, v_ego, 0.0, True, CarControllerParams.ANGLE_LIMITS)
    assert cc.angle_filter.x == pytest.approx(command, abs=1e-5)
    assert cc.apply_angle_last == pytest.approx(reference, abs=1e-4)


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
def test_angle_filter_starts_from_the_command_when_lateral_engages(platform):
  ci = ready_interface(platform)
  for _ in range(5):
    drive(ci, 3.0, 35.0, active=False)
  cc = drive(ci, 3.0, 35.0)
  assert cc.angle_filter.x == pytest.approx(35.0)
