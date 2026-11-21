"""The Tucson's slow-turn steering terms: nothing outside slow, tight turns; the right size and direction inside; never a jump."""
import math

import numpy as np
import pytest

from iqpilot.cereal import car, log
from iqpilot.selfdrive.controls.lib import latcontrol_torque
from iqpilot.selfdrive.controls.lib.latcontrol_torque import LAT_TUNE_V10, TUCSON_FINGERPRINT
from iqpilot.selfdrive.iqmodeld.config import ModelConstants

DT = 0.01
LAT_DELAY = 0.15
TUNE = LAT_TUNE_V10[TUCSON_FINGERPRINT]
SLOW = TUNE["speed_weight"][0][0] - 2.0          # m/s, in full use
FAST = TUNE["speed_weight"][0][-1]               # m/s, not used from here up
PREVIEW = TUNE["preview"]
T = np.array(ModelConstants.T_IDXS)


def pair(controller_factory, monkeypatch):
  """The controller as shipped and one built without the slow-turn table, which is the controller as it was."""
  new, vm, cp = controller_factory(TUCSON_FINGERPRINT)
  with monkeypatch.context() as patch:
    patch.setattr(latcontrol_torque, "LAT_TUNE_V10", {})
    old, _, _ = controller_factory(TUCSON_FINGERPRINT)
  assert new.v10 is not None and old.v10 is None
  return new, old, vm, cp


def plan(now, later):
  """A driving-model packet whose planned lateral acceleration goes from `now` at the preview's start to `later` at its end."""
  packet = log.ModelDataV2.new_message()
  packet.orientation.x = [0.0] * len(T)
  packet.orientation.y = [0.0] * len(T)
  # a straight line through the two points, so reading it back between the model's time steps is exact
  packet.acceleration.y = [float(now + (later - now) * (t - PREVIEW["from_s"]) / (PREVIEW["to_s"] - PREVIEW["from_s"])) for t in T]
  return packet


def drive(controller, vm, cp, speed, asked, got=None, packet=None, pressed=False, active=True):
  """Ask for a lateral acceleration profile (m/s^2, + right) while the wheel delivers `got` (default: exactly what is asked).
  Returns the torque commands (+ left, as sent to the car)."""
  live = log.VehicleParameters.new_message(stiffnessFactor=1.0, steerRatio=cp.steerRatio, roll=0.0)
  got = asked if got is None else got
  controller.nnff_assist.update_model_v2(packet)
  torques = []
  for a, g in zip(asked, got, strict=True):
    angle = math.degrees(vm.get_steer_from_curvature(-float(g) / speed ** 2, speed, 0.0))
    state = car.CarState.new_message(vEgo=speed, steeringAngleDeg=angle, steeringPressed=pressed)
    torque, _, _ = controller.update(active, state, vm, live, False, float(a) / speed ** 2, None, False, LAT_DELAY)
    torques.append(torque)
  return np.array(torques)


def hold(value, seconds):
  return np.full(int(round(seconds / DT)), float(value))


def ramp(start, end, rate):
  steps = max(int(round(abs(end - start) / rate / DT)), 1)
  return np.linspace(start, end, steps + 1)[1:]


def wheel_angle(vm, speed, lat_accel):
  return abs(math.degrees(vm.get_steer_from_curvature(-lat_accel / speed ** 2, speed, 0.0)))


def test_only_the_tucson_has_the_table_and_it_is_usable(controller_factory):
  assert set(LAT_TUNE_V10) == {TUCSON_FINGERPRINT}
  assert controller_factory(TUCSON_FINGERPRINT)[0].v10 is not None
  for platform in ("HYUNDAI_KONA_EV", "KIA_K5_2021", "TOYOTA_RAV4"):
    assert controller_factory(platform)[0].v10 is None
  assert 0.1 < TUNE["turn_friction"] <= 0.25                       # never more than the friction band found in the logs
  assert TUNE["speed_weight"][1] == [1.0, 0.0] and TUNE["angle_weight"][1] == [0.0, 1.0]
  assert PREVIEW["deadzone"] > 0.0 and PREVIEW["to_s"] > PREVIEW["from_s"]


@pytest.mark.parametrize("speed", [FAST, 13.0, 20.0, 30.0])
def test_above_its_speed_range_everything_is_exactly_as_before(controller_factory, monkeypatch, speed):
  new, old, vm, cp = pair(controller_factory, monkeypatch)
  rng = np.random.default_rng(5)
  asked = np.r_[hold(0.0, 0.5), ramp(0.0, 2.5, 1.0), hold(2.5, 1.0), ramp(2.5, -1.0, 2.0), np.clip(np.cumsum(rng.normal(0.0, 0.02, 800)), -2.0, 2.0)]
  got = 0.8 * asked
  easing = plan(2.5, 0.5)                                            # a plan that would trigger the early release at low speed
  assert (drive(new, vm, cp, speed, asked, got, easing) == drive(old, vm, cp, speed, asked, got, easing)).all()


def test_with_the_wheel_near_centre_everything_is_exactly_as_before(controller_factory, monkeypatch):
  new, old, vm, cp = pair(controller_factory, monkeypatch)
  small = 0.3
  assert wheel_angle(vm, SLOW, small) < TUNE["angle_weight"][0][0]
  rng = np.random.default_rng(6)
  asked = np.clip(np.cumsum(rng.normal(0.0, 0.01, 2000)), -small, small)
  easing = plan(0.3, -0.3)
  assert (drive(new, vm, cp, SLOW, asked, None, easing) == drive(old, vm, cp, SLOW, asked, None, easing)).all()


@pytest.mark.parametrize("side", [1.0, -1.0])
def test_winding_on_and_unwinding_get_the_friction_torque_in_the_right_direction(controller_factory, monkeypatch, side):
  new, old, vm, cp = pair(controller_factory, monkeypatch)
  speed, turn = SLOW, 2.0 * side
  assert wheel_angle(vm, speed, abs(turn) * 0.7) > TUNE["angle_weight"][0][-1]
  extra_expected = TUNE["turn_friction"] - new.friction_scale * float(np.interp(speed, *latcontrol_torque.LAT_TUNE_V7[TUCSON_FINGERPRINT]["friction_speed"]))
  assert extra_expected > 0.05
  # the car delivers less than asked: friction has to be overcome toward more turn
  asked, short = hold(turn, 3.0), hold(0.7 * turn, 3.0)
  more = drive(new, vm, cp, speed, asked, short) - drive(old, vm, cp, speed, asked, short)
  assert more[-1] == pytest.approx(-side * extra_expected, abs=1e-6)      # torque is + left, the turn is + right
  # the car delivers more than asked: friction has to be overcome back toward centre
  for controller in (new, old):
    drive(controller, vm, cp, speed, hold(0.0, 0.01), active=False)
  beyond = hold(1.4 * turn, 3.0)
  less = drive(new, vm, cp, speed, asked, beyond) - drive(old, vm, cp, speed, asked, beyond)
  assert less[-1] == pytest.approx(side * extra_expected, abs=1e-6)


def test_the_friction_torque_comes_in_gradually(controller_factory, monkeypatch):
  new, old, vm, cp = pair(controller_factory, monkeypatch)
  asked = np.r_[hold(0.0, 0.5), ramp(0.0, 2.0, 1.5), hold(2.0, 1.0), ramp(2.0, 0.0, 1.5), hold(0.0, 1.0)]
  got = np.r_[hold(0.0, 0.5), ramp(0.0, 1.6, 1.2), hold(1.6, 1.0), ramp(1.6, 0.0, 1.2), hold(0.0, 1.0)]
  change = drive(new, vm, cp, SLOW, asked, got) - drive(old, vm, cp, SLOW, asked, got)
  assert np.abs(change).max() <= TUNE["turn_friction"] + 1e-6
  assert np.abs(np.diff(change)).max() < 0.02                         # the car's own rate limit is 0.007-0.011 per frame


def test_a_hand_on_the_wheel_switches_the_friction_torque_off(controller_factory, monkeypatch):
  new, old, vm, cp = pair(controller_factory, monkeypatch)
  asked, short = hold(2.0, 2.0), hold(1.4, 2.0)
  assert (drive(new, vm, cp, SLOW, asked, short, pressed=True) == drive(old, vm, cp, SLOW, asked, short, pressed=True)).all()


def test_the_plan_easing_the_turn_leads_the_request_down_by_its_own_change(controller_factory, monkeypatch):
  new, old, vm, cp = pair(controller_factory, monkeypatch)
  monkeypatch.setitem(new.v10, "turn_friction", 0.0)                  # look at the preview alone
  for side in (1.0, -1.0):
    turn = 2.0 * side
    easing = plan(turn, turn - side * 0.8)                            # the plan says 0.8 less turn within the preview
    drive(new, vm, cp, SLOW, hold(turn, 2.0), None, easing)
    assert new._turn_preview.x == pytest.approx(-(0.8 - PREVIEW["deadzone"]), abs=1e-3)
    assert side * new.lat_accel_request_buffer[-1] == pytest.approx(2.0 - (0.8 - PREVIEW["deadzone"]), abs=1e-3)
    drive(new, vm, cp, SLOW, hold(0.0, 0.01), active=False)
    assert new._turn_preview.x == 0.0


def test_the_preview_never_adds_turn_never_crosses_straight_and_ignores_small_changes(controller_factory, monkeypatch):
  new, old, vm, cp = pair(controller_factory, monkeypatch)
  monkeypatch.setitem(new.v10, "turn_friction", 0.0)
  turn = hold(2.0, 2.0)
  for packet in (plan(2.0, 3.0), plan(2.0, 2.0 - 0.9 * PREVIEW["deadzone"]), None):       # more turn ahead, a small easing, no plan at all
    assert (drive(new, vm, cp, SLOW, turn, None, packet) == drive(old, vm, cp, SLOW, turn, None, packet)).all()
    for controller in (new, old):
      drive(controller, vm, cp, SLOW, hold(0.0, 0.01), active=False)
  drive(new, vm, cp, SLOW, hold(2.0, 2.0), None, plan(2.0, -3.0))                         # the plan swings to the other side
  assert new._turn_preview.x == pytest.approx(-PREVIEW["max"], abs=1e-3)
  drive(new, vm, cp, SLOW, hold(0.0, 0.01), active=False)
  drive(new, vm, cp, SLOW, hold(0.6, 2.0), hold(2.0, 2.0), plan(0.6, -3.0))               # asked for less than the cap, wheel still wound on
  assert new.lat_accel_request_buffer[-1] == 0.0


def test_the_preview_comes_in_and_goes_out_without_a_jump(controller_factory, monkeypatch):
  new, old, vm, cp = pair(controller_factory, monkeypatch)
  monkeypatch.setitem(new.v10, "turn_friction", 0.0)
  turn = hold(2.0, 1.0)
  drive(new, vm, cp, SLOW, turn, None, plan(2.0, 2.0))
  requests = []
  for packet in (plan(2.0, 0.8), plan(2.0, 2.0)):
    for _ in range(60):
      drive(new, vm, cp, SLOW, turn[:1], None, packet)
      requests.append(new.lat_accel_request_buffer[-1])
  assert np.abs(np.diff(requests)).max() < 0.12                       # at most 1 m/s^2 through a 0.1 s lag
  assert requests[59] < 1.1 and requests[-1] > 1.99
