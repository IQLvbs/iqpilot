"""Tucson pull-away shaping and jerk limits: only a launch from rest is shaped, never above the request, braking keeps its authority."""
import random
from types import SimpleNamespace

import numpy as np
import pytest

from iqdbc.car.hyundai import hyundaicanfd
from iqdbc.car.hyundai.carcontroller import HyundaiJerk, LongCtrlState
from iqdbc.car.hyundai.tucson_longitudinal import (
  BRAKE_JERK, BUILD_JERK, CAP_2ND, CAP_ACCEL, CAP_SPEED, CAUGHT_UP, CROSS_JERK, EASE_JERK, EASE_SPEED, END_SPEED, FULL_SPEED, JERK_MAX,
  LAUNCH_DT, LAUNCH_JERK, MAX_TIME, ONSET_JERK, ONSET_MIN_ACCEL, ONSET_MIN_SPEED, RELEASE_JERK, START_SPEED, TRAIL, TucsonLaunch, first_gear_cap,
  jerk_limits, second_gear_cap,
)
from iqdbc.car.hyundai.values import HyundaiFlags

CAP_START, CAP_SHIFT = CAP_ACCEL
CANFD = SimpleNamespace(flags=int(HyundaiFlags.CANFD))


def run(seq, value=-2.0):
  """seq: (request, speed) per SCC frame. Returns per frame (value sent, jerk_u, cap, active)."""
  launch, out = TucsonLaunch(), []
  for accel, v_ego in seq:
    jerk_u, cap = launch.update(accel, value, v_ego, False)
    value = hyundaicanfd.apply_accel_jerk_limit(accel if cap is None else min(accel, cap), value, 0.8 if jerk_u is None else jerk_u, 2.0)
    out.append((value, jerk_u, cap, launch.active))
  return out


def test_starts_at_rest_from_a_braking_hold_without_a_step():
  value, jerk_u, cap, active = run([(2.0, 0.0)] * 5)[0]
  assert active and jerk_u == RELEASE_JERK and cap == CAP_START
  assert value == pytest.approx(-2.0 + RELEASE_JERK * LAUNCH_DT)


def test_release_then_build_to_the_first_gear_cap_and_hold_it():
  out = run([(2.0, 0.0)] * 150)
  values = np.array([o[0] for o in out])
  steps = np.diff(values)
  assert np.allclose(steps[values[:-1] < -1e-9], RELEASE_JERK * LAUNCH_DT)
  assert np.allclose(steps[(values[:-1] > 1e-9) & (values[1:] < CAP_START - 1e-9)], LAUNCH_JERK * LAUNCH_DT)
  assert values.max() == pytest.approx(CAP_START)   # held at the cap, well under the 2.0 request
  assert all(o[3] for o in out)


def test_caps_rise_with_speed():
  assert first_gear_cap(0.0) == CAP_START and first_gear_cap(CAP_SPEED[1] + 1.0) == CAP_SHIFT
  assert first_gear_cap(sum(CAP_SPEED) / 2) == pytest.approx((CAP_START + CAP_SHIFT) / 2)
  assert second_gear_cap(EASE_SPEED - 1.0, 2.0) == pytest.approx(CAP_2ND) and second_gear_cap(FULL_SPEED + 1.0, 2.0) == pytest.approx(2.0)
  assert second_gear_cap((EASE_SPEED + FULL_SPEED) / 2, 2.0) == pytest.approx((CAP_2ND + 2.0) / 2)
  assert second_gear_cap(EASE_SPEED + 0.5, 1.3) == 1.3   # a request under CAP_2ND is the cap
  for cap in (first_gear_cap, lambda v: second_gear_cap(v, 2.2)):
    assert np.all(np.diff([cap(v) for v in np.linspace(0.0, FULL_SPEED + 1.0, 80)]) >= -1e-12)
  assert CAP_2ND >= first_gear_cap(EASE_SPEED) - 1e-9 and FULL_SPEED < END_SPEED


def test_holds_through_the_shift_then_rises_with_speed_and_ends_when_caught_up():
  seq = [(2.0, 0.0)] * 100 + [(2.0, EASE_SPEED + 0.05)] * 100 + [(2.0, EASE_SPEED + 0.05 + 0.02 * k) for k in range(1, 200)]
  out = run(seq)
  values = np.array([o[0] for o in out])
  assert values[99] == pytest.approx(CAP_START) and out[100][1] == EASE_JERK
  assert np.all(np.diff(values[99:200]) <= EASE_JERK * LAUNCH_DT + 1e-9)
  assert values[199] == pytest.approx(second_gear_cap(EASE_SPEED + 0.05, 2.0), abs=1e-6) and values[199] < 1.8
  ended = next(i for i in range(200, len(out)) if not out[i][3])
  assert values[ended - 1] >= 2.0 - CAUGHT_UP - 1e-9 and seq[ended][1] <= FULL_SPEED + 0.1
  assert all(values[i] <= second_gear_cap(seq[i][1], 2.0) + 1e-9 for i in range(200, ended))


def test_the_cap_never_pulls_the_value_down_but_a_lower_request_does():
  launch = TucsonLaunch()
  launch.update(2.0, -2.0, 0.0, False)
  launch.easing = True
  assert second_gear_cap(EASE_SPEED + 0.1, 2.3) < 1.8
  jerk_u, cap = launch.update(2.3, 1.95, EASE_SPEED + 0.1, False)
  assert launch.active and jerk_u == EASE_JERK and cap == pytest.approx(1.95)
  assert launch.update(1.2, 1.95, EASE_SPEED + 0.1, False) == (None, None) and not launch.active   # caught up: stock follows it down


def test_never_above_the_request_or_the_caps():
  rng = random.Random(4)
  for _ in range(200):
    v, seq = 0.0, []
    for _ in range(400):
      v = max(0.0, v + rng.uniform(-0.01, 0.06))
      seq.append((rng.choice([0.4, 1.0, 1.6, 2.0, 2.5]) if rng.random() < 0.02 or not seq else seq[-1][0], v))
    value_before = -2.0
    for (accel, _), (value, _, cap, active) in zip(seq, run(seq), strict=True):
      assert value <= accel + 1e-9 or value <= value_before + 1e-9
      if active and cap is not None and value > value_before:
        assert value <= cap + 1e-9
      value_before = value


@pytest.mark.parametrize("accel,blocked", [(2.0, True), (0.0, False), (-0.5, False), (float("nan"), False)])
def test_a_blocker_or_a_request_that_is_not_positive_ends_it_at_once(accel, blocked):
  launch = TucsonLaunch()
  assert launch.update(2.0, -2.0, 0.0, False)[0] == RELEASE_JERK
  assert launch.update(accel, -1.9, 0.0, blocked) == (None, None)
  assert not launch.active and not launch.easing and launch.time == 0.0


def test_only_a_launch_from_rest_is_shaped():
  assert TucsonLaunch().update(2.0, -0.5, START_SPEED + 0.1, False) == (None, None)   # already moving
  assert TucsonLaunch().update(2.0, 0.3, 0.0, False) == (None, None)                  # not coming out of a hold


def test_ends_past_end_speed_and_after_max_time():
  launch = TucsonLaunch()
  launch.update(2.0, -2.0, 0.0, False)
  assert launch.update(2.0, 1.0, END_SPEED + 0.1, False) == (None, None)
  launch.update(2.0, -2.0, 0.0, False)
  frames = 0
  while launch.update(2.0, 0.5, 1.0, False) != (None, None):
    frames += 1
  assert frames * LAUNCH_DT == pytest.approx(MAX_TIME, abs=2 * LAUNCH_DT)


def test_jerk_limits_fcw_and_gas_override():
  assert jerk_limits(0.0, -1.0, 0.0, 10.0, True, False) == (JERK_MAX, JERK_MAX)
  assert jerk_limits(0.0, -1.0, 0.0, 10.0, True, True) == (JERK_MAX, JERK_MAX)
  assert jerk_limits(0.0, 1.0, 0.0, 10.0, False, True) == (0.5, 0.5)


def test_acceleration_builds_softly_at_low_speed_and_never_crosses_into_gas_fast():
  assert [jerk_limits(0.0, 1.0, 0.5, v, False, False)[0] for v in (0.0, 2.0, 5.0, 20.0)] == [BUILD_JERK[0], BUILD_JERK[1], BUILD_JERK[2], BUILD_JERK[2]]
  assert jerk_limits(0.0, 1.0, -0.5, 20.0, False, False)[0] == CROSS_JERK   # request positive, command still braking
  assert jerk_limits(0.0, -0.5, -1.0, 20.0, False, False)[0] == CROSS_JERK  # a brake release
  assert jerk_limits(2.0, 1.0, 0.5, 0.0, False, False)[0] == 4.0            # the planner's own jerk still opens it
  assert jerk_limits(9.0, 1.0, 0.5, 0.0, False, False)[0] == JERK_MAX


def test_braking_starts_gently_and_opens_as_the_command_trails_the_request():
  v = ONSET_MIN_SPEED + 5.0
  assert jerk_limits(0.0, -1.0, -1.0, v, False, False)[1] == ONSET_JERK
  assert jerk_limits(0.0, -1.0, -1.0 + TRAIL, v, False, False)[1] == pytest.approx(BRAKE_JERK)
  assert jerk_limits(0.0, -2.0, -1.0, v, False, False)[1] == pytest.approx(BRAKE_JERK + 2.0 * (1.0 - TRAIL))
  limits = [jerk_limits(0.0, -2.4, -2.4 + lag, v, False, False)[1] for lag in np.linspace(0.0, 2.4, 60)]
  assert np.all(np.diff(limits) >= 0.0) and limits[0] == ONSET_JERK and limits[-1] == JERK_MAX


@pytest.mark.parametrize("accel,v", [(ONSET_MIN_ACCEL, 20.0), (-3.5, 20.0), (-1.0, ONSET_MIN_SPEED - 0.1), (-1.0, 0.5)])
def test_urgent_requests_and_stops_keep_the_full_brake_limit(accel, v):
  for lag in (0.0, 0.3, 1.5):
    assert jerk_limits(0.0, accel, accel + lag, v, False, False)[1] >= BRAKE_JERK
  assert jerk_limits(-1.2, accel, accel, v, False, False)[1] == pytest.approx(4.8)   # the planner's jerk opens it as in stock


def test_only_a_car_with_its_own_limits_leaves_the_stock_ones():
  jerk = HyundaiJerk()
  assert jerk.car_limits is None and jerk.launch_cap is None
  actuators = SimpleNamespace(longControlState=LongCtrlState.pid, jerk=-0.2)
  CC = SimpleNamespace(longComfortMode=False, hudControl=SimpleNamespace(visualAlert="none"), cruiseControl=SimpleNamespace(override=False))
  CC_IQ = SimpleNamespace(longitudinalComfort=SimpleNamespace(jerkUp=0.0, jerkDown=0.0, accelDeviationAbove=0.0, accelDeviationBelow=0.0,
                                                               valid=False, bypassJerkLimit=False))
  CS = SimpleNamespace(out=SimpleNamespace(aEgo=0.0, vEgo=20.0), softHoldActive=0)
  jerk.make_jerk(CANFD, CS, -1.0, actuators, CC, CC_IQ)
  stock = (jerk.jerk_u, jerk.jerk_l)
  jerk.accel_value_last = -1.0
  jerk.car_limits = jerk_limits
  jerk.make_jerk(CANFD, CS, -1.0, actuators, CC, CC_IQ)
  assert stock == (0.5, 1.2) and (jerk.jerk_u, jerk.jerk_l) == (CROSS_JERK, ONSET_JERK)


class Car:
  """A camera-SCC car with cruise available, as create_acc_control_scc2 needs it."""
  def __init__(self, v_ego=0.0):
    self.scc_control = {"COUNTER": 0, "aReqValue": 0.0, "aReqRaw": 0.0, "InfoDisplay": 0, "ACC_ObjRelSpd": 0.0}
    self.softHoldActive = 0
    self.paddle_button_prev = 0
    self.canfdSccHoldActive = False
    wheels = SimpleNamespace(fl=v_ego, fr=v_ego, rl=v_ego, rr=v_ego)
    self.out = SimpleNamespace(vEgo=v_ego, aEgo=0.0, vEgoRaw=v_ego, wheelSpeeds=wheels, carrotCruise=0, gasPressed=False, brakePressed=False,
                               brakeHoldActive=False, parkingBrake=False, canValid=True, gearShifter="drive",
                               cruiseState=SimpleNamespace(available=True, standstill=v_ego < 0.05))


def send(jerk, accel, value, CS):
  packer = SimpleNamespace(make_can_msg=lambda name, bus, values: dict(values))
  hud = SimpleNamespace(leadDistanceBars=2, leadVisible=False)
  return hyundaicanfd.create_acc_control_scc2(packer, SimpleNamespace(ECAN=0), True, value, accel, False, False, 30, hud, jerk, CS, None)


def test_the_raw_request_follows_the_value_only_while_a_launch_is_shaped():
  jerk = HyundaiJerk()
  jerk.carrot_cruise = 0
  jerk.jerk_u = jerk.jerk_l = 2.0
  msg, value = send(jerk, 2.0, -1.0, Car())
  assert (msg["aReqRaw"], value) == (2.0, pytest.approx(-1.0 + 2.0 * LAUNCH_DT))   # stock: the raw request is the full request
  jerk.launch_cap = 1.2
  msg, value = send(jerk, 2.0, 1.19, Car())
  assert value == pytest.approx(1.2) and msg["aReqRaw"] == value                 # capped, and raw follows the value
  msg, value = send(jerk, 0.8, 0.79, Car())
  assert value == pytest.approx(0.8) and msg["aReqRaw"] == value                 # a request under the cap is never exceeded
