"""The Tucson's in-curve feed-forward: off where it should be off, the right size where it is on, and never a jump."""
import math

import numpy as np
import pytest

from iqdbc.car.hyundai.values import CarControllerParams
from iqpilot.cereal import car, log
from iqpilot.selfdrive.controls.lib import latcontrol_torque
from iqpilot.selfdrive.controls.lib.curve_feedforward import ENTER_LAT_ACCEL, ENTER_TAU_S
from iqpilot.selfdrive.controls.lib.latcontrol_torque import LAT_TUNE_V8, LAT_TUNE_V9, TUCSON_FINGERPRINT

DT = 0.01
LAT_DELAY = 0.15
SPEED_ON = LAT_TUNE_V9[TUCSON_FINGERPRINT]["speed_weight"][0][-1]     # from here up the curve feed-forward is fully in use
SPEED_OFF = LAT_TUNE_V9[TUCSON_FINGERPRINT]["speed_weight"][0][0]     # at or below this it is not used at all


def tucson_pair(controller_factory, monkeypatch):
  """The controller as shipped and one built without the curve table, which is the controller as it was."""
  new, vm, cp = controller_factory(TUCSON_FINGERPRINT)
  with monkeypatch.context() as patch:
    patch.setattr(latcontrol_torque, "LAT_TUNE_V9", {})
    old, _, _ = controller_factory(TUCSON_FINGERPRINT)
  assert new.v9 is not None and old.v9 is None
  return new, old, vm, cp


def drive(controller, vm, cp, speed, lat_accels, active=True):
  """Feed a requested cornering profile (m/s^2, + is right). The wheel is always where the request puts it, so the feedback
  terms depend only on the profile and are the same for any two controllers given the same one. Returns the torque commands."""
  live = log.VehicleParameters.new_message(stiffnessFactor=1.0, steerRatio=cp.steerRatio, roll=0.0)
  torques = []
  for lat_accel in lat_accels:
    curvature = float(lat_accel) / speed ** 2
    angle = math.degrees(vm.get_steer_from_curvature(-curvature, speed, 0.0))
    state = car.CarState.new_message(vEgo=speed, steeringAngleDeg=angle)
    torque, _, _ = controller.update(active, state, vm, live, False, curvature, None, False, LAT_DELAY)
    torques.append(torque)
  return np.array(torques)


def ramp(start, end, rate):
  steps = max(int(round(abs(end - start) / rate / DT)), 1)
  return np.linspace(start, end, steps + 1)[1:]


def hold(value, seconds):
  return np.full(int(round(seconds / DT)), float(value))


def curve(peak, rate=0.8, held_s=3.0, after_s=9.0):
  return np.r_[hold(0.0, 1.0), ramp(0.0, peak, rate), hold(peak, held_s), ramp(peak, 0.0, rate), hold(0.0, after_s)]


def torque_per_lat_accel_before(speed):
  tune = LAT_TUNE_V8[TUCSON_FINGERPRINT]
  return float(np.interp(speed, *tune["ff_torque_scale_speed"]) / np.interp(speed, *tune["ff_lat_accel_factor_speed"]))


def stiffness(speed):
  return float(np.interp(speed, *LAT_TUNE_V9[TUCSON_FINGERPRINT]["stiffness_speed"]))


def test_only_the_tucson_has_a_curve_table(controller_factory):
  assert set(LAT_TUNE_V9) == {TUCSON_FINGERPRINT}
  assert controller_factory(TUCSON_FINGERPRINT)[0].v9 is not None
  for platform in ("HYUNDAI_KONA_EV", "KIA_K5_2021", "GENESIS_G80", "TOYOTA_RAV4"):
    assert controller_factory(platform)[0].v9 is None


def test_the_tables_are_usable():
  tune = LAT_TUNE_V9[TUCSON_FINGERPRINT]
  speeds, values = tune["stiffness_speed"]
  assert len(speeds) == len(values) and list(speeds) == sorted(speeds) and min(values) > 0.0
  weight_speeds, weights = tune["speed_weight"]
  assert list(weight_speeds) == sorted(weight_speeds) and weights[0] == 0.0 and weights[-1] == 1.0
  assert speeds[0] >= weight_speeds[0]            # nothing below the measured range gets full weight from a made-up stiffness
  # the reason for the table: between 25 and 50 mph the old feed-forward is steeper than the cornering itself takes
  for speed in (12.1, 14.8, 17.5, 20.6):
    assert 1.2 < torque_per_lat_accel_before(speed) / stiffness(speed) < 1.6


@pytest.mark.parametrize("speed", [6.0, 13.0, 20.0, 30.0])
def test_lane_keeping_is_exactly_as_before(controller_factory, monkeypatch, speed):
  new, old, vm, cp = tucson_pair(controller_factory, monkeypatch)
  rng = np.random.default_rng(3)
  wander = np.clip(np.cumsum(rng.normal(0.0, 0.01, 3000)), -(ENTER_LAT_ACCEL - 0.1), ENTER_LAT_ACCEL - 0.1)
  assert (drive(new, vm, cp, speed, wander) == drive(old, vm, cp, speed, wander)).all()
  assert new.curve_weight.weight == 0.0


@pytest.mark.parametrize("speed", [5.0, SPEED_OFF])
def test_below_its_speed_range_a_curve_is_exactly_as_before(controller_factory, monkeypatch, speed):
  new, old, vm, cp = tucson_pair(controller_factory, monkeypatch)
  profile = curve(2.0)
  assert (drive(new, vm, cp, speed, profile) == drive(old, vm, cp, speed, profile)).all()


@pytest.mark.parametrize("speed", [SPEED_ON, 14.8, 17.5, 24.0])
@pytest.mark.parametrize("peak", [1.5, -1.5])
def test_in_a_curve_the_feedforward_is_the_stiffness_times_the_request(controller_factory, monkeypatch, speed, peak):
  new, old, vm, cp = tucson_pair(controller_factory, monkeypatch)
  profile = np.r_[hold(0.0, 1.0), ramp(0.0, peak, 0.8), hold(peak, 3.0)]
  torque_new, torque_old = drive(new, vm, cp, speed, profile), drive(old, vm, cp, speed, profile)
  assert new.curve_weight.weight == pytest.approx(1.0, abs=1e-4)
  request = peak - new.torque_params.latAccelOffset
  # update() returns the torque with the opposite sign to the request
  assert torque_new[-1] - torque_old[-1] == pytest.approx(-(stiffness(speed) - torque_per_lat_accel_before(speed)) * request, abs=1e-5)
  assert abs(torque_new[-1]) < abs(torque_old[-1])   # at these speeds: less torque than before for the same curve
  assert np.sign(torque_new[-1]) == np.sign(torque_old[-1])


def test_between_the_speed_points_it_is_partly_in(controller_factory, monkeypatch):
  new, old, vm, cp = tucson_pair(controller_factory, monkeypatch)
  speed = (SPEED_OFF + SPEED_ON) / 2
  profile = np.r_[hold(0.0, 1.0), ramp(0.0, 1.5, 0.8), hold(1.5, 3.0)]
  change = drive(new, vm, cp, speed, profile)[-1] - drive(old, vm, cp, speed, profile)[-1]
  request = 1.5 - new.torque_params.latAccelOffset
  assert change == pytest.approx(-0.5 * (stiffness(speed) - torque_per_lat_accel_before(speed)) * request, abs=1e-5)


@pytest.mark.parametrize("speed", [SPEED_ON, 15.0, 22.0, 30.0])
@pytest.mark.parametrize("peak", [2.5, -2.5])
def test_the_change_comes_in_and_goes_out_without_a_jump(controller_factory, monkeypatch, speed, peak):
  new, old, vm, cp = tucson_pair(controller_factory, monkeypatch)
  profile = curve(peak, rate=1.0)
  change = drive(new, vm, cp, speed, profile) - drive(old, vm, cp, speed, profile)
  assert (change[:100] == 0.0).all()               # straight before the curve: the same torque as before
  assert change[-1] == 0.0                         # and after it, once the curve has gone
  full = abs((stiffness(speed) - torque_per_lat_accel_before(speed)) * (peak - new.torque_params.latAccelOffset))
  assert np.abs(change).max() == pytest.approx(full, rel=1e-3)   # in between it reached all of it and no more
  # the car's own limit on how fast the torque command may rise is STEER_DELTA_UP counts of STEER_MAX per frame;
  # what this adds or removes per frame stays under a third of that
  limits = CarControllerParams(cp)
  assert np.abs(np.diff(change)).max() < limits.STEER_DELTA_UP / limits.STEER_MAX / 3


def test_engaging_in_the_middle_of_a_curve_starts_from_the_old_feedforward(controller_factory, monkeypatch):
  new, old, vm, cp = tucson_pair(controller_factory, monkeypatch)
  speed, level = 15.0, 2.0
  waiting = hold(level, 1.0)
  assert (drive(new, vm, cp, speed, waiting, active=False) == 0.0).all()
  drive(old, vm, cp, speed, waiting, active=False)
  assert new.curve_weight.weight == 0.0 and not new.curve_weight.in_curve
  profile = hold(level, 3.0)
  change = drive(new, vm, cp, speed, profile) - drive(old, vm, cp, speed, profile)
  full = -(stiffness(speed) - torque_per_lat_accel_before(speed)) * (level - new.torque_params.latAccelOffset)
  assert change[0] == pytest.approx(full * DT / ENTER_TAU_S, rel=1e-6)   # the first frame carries one small step of the blend
  assert np.abs(np.diff(change)).max() <= abs(full) * DT / ENTER_TAU_S + 1e-12
  assert change[-1] == pytest.approx(full, rel=1e-3)


def test_going_inactive_forgets_the_curve(controller_factory, monkeypatch):
  new, _, vm, cp = tucson_pair(controller_factory, monkeypatch)
  drive(new, vm, cp, 15.0, np.r_[ramp(0.0, 2.0, 1.0), hold(2.0, 1.0)])
  assert new.curve_weight.in_curve and new.curve_weight.weight > 0.9
  drive(new, vm, cp, 15.0, hold(2.0, 0.01), active=False)
  assert not new.curve_weight.in_curve and new.curve_weight.weight == 0.0
  drive(new, vm, cp, 15.0, np.r_[ramp(0.0, 2.0, 1.0), hold(2.0, 1.0)])
  new.reset()
  assert not new.curve_weight.in_curve and new.curve_weight.weight == 0.0
