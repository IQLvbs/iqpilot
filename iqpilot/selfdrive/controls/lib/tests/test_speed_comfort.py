import numpy as np
import pytest

from iqpilot.selfdrive.controls.lib.speed_comfort import (
  BACKOFF_ACCEL, BACKOFF_BEND_LAT_BP, BACKOFF_MIN_SPEED, BACKOFF_SPEED_BP, BEND_SHAPE, PICKUP_JERK, PICKUP_MARGIN, PICKUP_PATIENCE, RETURN_SHAPE,
  RUN_AHEAD_MARGIN, RUN_AHEAD_MIN_ASK, RUN_AHEAD_OPEN, RUN_AHEAD_SHORT, RUN_AHEAD_TIME, TAKEOVER_MIN_SPEED, TAKEOVER_TIME, TURN_ACCEL_V,
  TURN_LAT_ACCEL_BP, PickupLimiter, cruise_shape,
)

DT = 0.05
SLOW = BACKOFF_SPEED_BP[0] - 3.0     # m/s, where the backing-off rule applies in full
FAST = BACKOFF_SPEED_BP[1] + 1.0     # m/s, where it does not apply



def test_shapes_are_gentler_than_stock_and_only_for_the_right_targets():
  assert cruise_shape(False, "none", False) is RETURN_SHAPE
  assert cruise_shape(True, "vision", False) is BEND_SHAPE
  for provider in ("none", "route", "mapbox", "offlineOsm", "camera"):
    assert cruise_shape(True, provider, False) is None        # a turn on a route must still be reached in time
  assert cruise_shape(False, "none", True) is None            # forced deceleration keeps the stock braking
  assert cruise_shape(True, "vision", True) is None
  for shape in (RETURN_SHAPE, BEND_SHAPE):
    assert -1.2 < shape.min_accel < 0.0 and 0.0 < shape.gain_above < 1.0 and 0.0 < shape.gain_below <= 1.0 and 0.0 < shape.jerk_brake < 0.8


def take_over(helper, v_ego=SLOW, a_ego=0.0):
  """Two frames with the planner following the car (cruise not in control), as during a driver override."""
  for _ in range(2):
    assert helper.limit_rise(1.5, a_ego, True, v_ego, a_ego, 0.0, False) == 1.5


class Car:
  """Delivers the request after a pause, then quickly: what the logs show after a lift."""
  def __init__(self, pause, a=0.0):
    self.a, self.pause, self.asked_for = a, pause, 0.0

  def step(self, request):
    self.asked_for = self.asked_for + DT if request > 0.15 else 0.0
    follow = request if self.asked_for >= self.pause else min(request, -0.1)
    self.a += (follow - self.a) * DT / 0.15
    return self.a


@pytest.mark.parametrize("target", [-3.5, -1.0, -0.01, 0.0])
def test_braking_and_coasting_pass_through_untouched(target):
  helper = PickupLimiter(DT)
  take_over(helper)
  for lateral in (0.0, 1.5, 3.0):
    for a_prev in (-2.0, 0.0, 1.5):
      assert helper.limit_rise(target, a_prev, False, SLOW, -1.0, lateral, False) == target


def test_it_never_asks_for_more_than_the_plan():
  rng = np.random.default_rng(1)
  helper = PickupLimiter(DT)
  out = 0.0
  for _ in range(4000):
    target = float(rng.uniform(-3.0, 2.0))
    reset = bool(rng.random() < 0.02)
    out = helper.limit_rise(target, out, reset, float(rng.uniform(0.0, 30.0)), float(rng.uniform(-3.0, 3.0)), float(rng.uniform(-3.5, 3.5)),
                            bool(rng.random() < 0.05))
    assert out <= target
    assert out == target or out >= 0.0


def test_steady_cruising_on_a_straight_road_is_untouched():
  helper = PickupLimiter(DT)
  for target in (0.6, 0.8, 1.2, 2.0):
    assert helper.limit_rise(target, target, False, 20.0, target, 0.0, False) == target
  assert helper.window == 0.0


def test_after_a_take_over_the_request_stays_close_to_what_the_car_delivers():
  helper = PickupLimiter(DT)
  take_over(helper, a_ego=0.0)
  car, out, outs, deliv = Car(pause=0.65), 0.0, [], []
  for _ in range(int(5.0 / DT)):
    out = helper.limit_rise(1.5, out, False, SLOW, car.a, 0.0, False)
    car.step(out)
    outs.append(out)
    deliv.append(car.a)
  outs, deliv = np.array(outs), np.array(deliv)
  pause = slice(0, int(0.6 / DT))
  assert outs[pause].max() <= PICKUP_MARGIN + PICKUP_PATIENCE * 0.6 + 1e-6   # during the drivetrain's pause the request waits low
  assert np.diff(outs).max() <= PICKUP_JERK * DT + 1e-9        # and it never steps up
  assert outs[-1] == 1.5 and helper.window == 0.0              # it gets there, and then lets go
  first_response = float(deliv[int(0.65 / DT) + 4])
  assert first_response < 0.6                                   # what the car first delivers is a fraction of the 1.5 asked for


def test_without_the_cap_the_same_car_gets_the_whole_request_at_once():
  car, deliv = Car(pause=0.65), []
  for _ in range(int(1.2 / DT)):
    deliv.append(car.step(1.5))
  assert deliv[int(0.65 / DT) + 4] > 1.0


def test_the_window_stays_open_until_the_request_has_caught_up_and_never_ends_with_a_step():
  helper = PickupLimiter(DT)
  take_over(helper)
  answers_at = TAKEOVER_TIME + 0.5                                # a car that only answers after the nominal window
  out, outs = 0.0, []
  for k in range(int(6.0 / DT)):
    out = helper.limit_rise(2.0, out, False, SLOW, 0.0 if k * DT < answers_at else out, 0.0, False)
    outs.append(out)
  outs = np.array(outs)
  just_before = outs[int((answers_at - 0.1) / DT)]
  assert just_before <= PICKUP_MARGIN + PICKUP_PATIENCE * answers_at + 1e-6
  assert np.diff(outs).max() <= PICKUP_JERK * DT + 1e-9
  assert outs[-1] == 2.0 and helper.window == 0.0


def test_a_car_that_never_answers_still_gets_the_request_without_a_step():
  helper = PickupLimiter(DT)
  take_over(helper)
  out, outs = 0.0, []
  for _ in range(int(8.0 / DT)):
    out = helper.limit_rise(2.0, out, False, SLOW, 0.0, 0.0, False)
    outs.append(out)
  outs = np.array(outs)
  assert outs[int(1.0 / DT)] <= PICKUP_MARGIN + PICKUP_PATIENCE * 1.0 + 1e-6
  assert np.diff(outs).max() <= PICKUP_JERK * DT + 1e-9
  assert outs[-1] == 2.0
  reached = np.argmax(outs >= 2.0) * DT
  assert reached == pytest.approx((2.0 - PICKUP_MARGIN) / PICKUP_PATIENCE, abs=0.2)


def test_a_take_over_near_standstill_is_a_launch_and_is_left_alone():
  helper = PickupLimiter(DT)
  take_over(helper, v_ego=TAKEOVER_MIN_SPEED - 0.5)
  assert helper.limit_rise(1.5, 0.0, False, TAKEOVER_MIN_SPEED - 0.5, 0.0, 0.0, False) == 1.5
  assert helper.limit_rise(2.0, 1.5, False, 1.0, 0.3, 0.0, False) == 2.0


def test_a_launch_from_rest_is_left_alone():
  helper = PickupLimiter(DT)
  v, out = 0.0, 0.0
  for k in range(int(4.0 / DT)):
    target = min(2.0, 2.7 * k * DT)                 # the plan is already pulling hard when the car passes walking pace
    out = helper.limit_rise(target, out, False, v, 0.0, 0.0, v < 0.1)   # even with a car that reports no acceleration
    assert out == target
    v += out * DT
  assert v > BACKOFF_MIN_SPEED


def test_pulling_again_after_backing_off_at_low_speed_is_held_to_the_car():
  helper = PickupLimiter(DT)
  out = 0.3
  for _ in range(40):
    out = helper.limit_rise(0.3, out, False, SLOW, 0.1, 0.0, False)     # backed off while moving; the car delivers 0.1
  assert out == 0.3 and BACKOFF_ACCEL > 0.3
  outs = []
  for _ in range(int(1.0 / DT)):
    out = helper.limit_rise(1.6, out, False, SLOW, 0.1, 0.0, False)     # the plan pulls again; the car has let go
    outs.append(out)
  assert max(outs) <= 0.1 + PICKUP_MARGIN + PICKUP_PATIENCE * 1.0 + 1e-3
  assert np.diff(outs).max() <= PICKUP_JERK * DT + 1e-9


def test_the_backing_off_rule_fades_out_with_speed():
  for v_ego, expect_full in ((FAST, True), (30.0, True)):
    helper = PickupLimiter(DT)
    out = 0.2
    for _ in range(10):
      out = helper.limit_rise(0.2, out, False, v_ego, 0.2, 0.0, False)
    assert (helper.limit_rise(1.4, out, False, v_ego, 0.2, 0.0, False) == 1.4) is expect_full
  helper = PickupLimiter(DT)
  mid = float(np.mean(BACKOFF_SPEED_BP))
  out = helper.limit_rise(0.2, 0.2, False, mid, 0.2, 0.0, False)
  out = helper.limit_rise(1.4, out, False, mid, 0.2, 0.0, False)
  assert 0.2 + PICKUP_JERK * DT < out < 1.4                     # half way: between the cap and the plan


def test_cornering_holds_acceleration_back():
  helper = PickupLimiter(DT)
  for lateral, cap in zip(TURN_LAT_ACCEL_BP, TURN_ACCEL_V, strict=True):
    for sign in (1.0, -1.0):
      assert helper.limit_rise(2.0, 2.0, False, 15.0, 2.0, sign * lateral, False) == pytest.approx(cap)
  assert helper.limit_rise(2.0, 2.0, False, 15.0, 2.0, 3.5, False) == pytest.approx(TURN_ACCEL_V[-1])
  assert helper.limit_rise(0.5, 0.5, False, 15.0, 0.5, 3.5, False) == 0.5


def test_a_reset_forgets_everything():
  helper = PickupLimiter(DT)
  take_over(helper)
  helper.limit_rise(1.5, 0.0, False, SLOW, 0.0, 0.0, False)
  assert helper.window > 0.0
  helper.limit_rise(1.5, 0.0, True, 0.5, 0.0, 0.0, False)       # cruise lets go near standstill
  assert helper.window == 0.0 and not helper.takeover and helper.held_for == 0.0


def test_the_backing_off_rule_also_acts_in_a_bend_at_any_speed():
  for lateral, held in ((BACKOFF_BEND_LAT_BP[1], True), (BACKOFF_BEND_LAT_BP[0], False), (0.0, False)):
    helper = PickupLimiter(DT)
    out = 0.2
    for _ in range(10):
      out = helper.limit_rise(0.2, out, False, FAST, 0.2, lateral, False)
    got = helper.limit_rise(0.9, out, False, FAST, 0.2, lateral, False)
    if held:
      assert got == pytest.approx(0.2 + PICKUP_JERK * DT)           # picks the drive up at the car's pace, not at once
    else:
      assert got == pytest.approx(0.9)                               # straight, or a gentle bend: as before


def planned_gap(helper, seconds, a_asked, a_car, v_ego=0.0, gap0=0.0):
  """The gap between the planned speed and the car the speed loop sees, with the planner's own integration and its
  2 s pull toward the car; helper=None for the release."""
  v_des = v_ego + gap0
  out = []
  for _ in range(int(round(seconds / DT))):
    v_des += (v_ego - v_des) * DT / 2.0
    if helper is not None:
      v_des = helper.limit_run_ahead(v_des, v_ego, a_asked, a_car, False)
    out.append(v_des - v_ego)
    v_des += a_asked * DT
  return np.array(out)


def test_the_planned_speed_waits_for_a_car_that_has_not_picked_up_the_drive():
  release = planned_gap(None, 1.2, 1.5, 0.0)
  helper = PickupLimiter(DT)
  held = planned_gap(helper, 1.2, 1.5, 0.0)
  assert release.max() > 1.0                                         # the release adds over 1 m/s^2 through the speed loop
  assert held.max() <= RUN_AHEAD_MARGIN + 1.5 * DT + 1e-9            # here at most the margin (plus one step of the plan)


def test_the_margin_opens_again_after_a_while_so_a_car_on_a_hill_gets_the_loops_help():
  helper = PickupLimiter(DT)
  gap = planned_gap(helper, RUN_AHEAD_TIME + 2.0, 1.0, 0.0)
  t = np.arange(len(gap)) * DT
  late = t > RUN_AHEAD_TIME + 1.0
  assert gap[late].min() > RUN_AHEAD_MARGIN + 0.5 * RUN_AHEAD_OPEN - 0.1
  assert np.diff(gap).max() <= 1.0 * DT + 1e-9                       # never a step


@pytest.mark.parametrize("a_asked,a_car", [(RUN_AHEAD_MIN_ASK, 0.0), (0.0, 0.0), (-1.0, 0.0), (1.0, 1.0 - RUN_AHEAD_SHORT + 0.05)])
def test_nothing_changes_while_braking_coasting_or_with_a_car_that_answers(a_asked, a_car):
  helper = PickupLimiter(DT)
  for _ in range(20):
    helper.a_ego_run_ahead.update(a_car)
  assert helper.limit_run_ahead(5.0, 3.0, a_asked, a_car, False) == 5.0


def test_it_only_ever_lowers_the_planned_speed_and_a_reset_passes_through():
  helper = PickupLimiter(DT)
  assert helper.limit_run_ahead(2.0, 3.0, 1.5, 0.0, False) == 2.0      # behind the car already: untouched
  assert helper.limit_run_ahead(5.0, 3.0, 1.5, 0.0, False) == pytest.approx(3.0 + RUN_AHEAD_MARGIN)
  assert helper.limit_run_ahead(5.0, 3.0, 1.5, 0.0, True) == 5.0
  assert helper.run_ahead_for == 0.0
