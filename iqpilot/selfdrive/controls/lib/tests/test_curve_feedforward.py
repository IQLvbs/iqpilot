import numpy as np
import pytest

from iqpilot.selfdrive.controls.lib.curve_feedforward import (
  ENTER_LAT_ACCEL,
  ENTER_TAU_S,
  LEAVE_HOLD_S,
  LEAVE_LAT_ACCEL,
  LEAVE_TAU_S,
  CurveWeight,
)

DT = 0.01


def run(helper, requests):
  return np.array([helper.update(float(r)) for r in requests])


def ramp(start, end, rate):
  """A request moving from start to end at `rate` m/s^3."""
  steps = max(int(round(abs(end - start) / rate / DT)), 1)
  return np.linspace(start, end, steps + 1)[1:]


def hold(value, seconds):
  return np.full(int(round(seconds / DT)), value)


def test_straight_road_never_gets_any_weight():
  rng = np.random.default_rng(0)
  helper = CurveWeight(DT)
  wander = np.clip(np.cumsum(rng.normal(0.0, 0.01, 60_000)), -(ENTER_LAT_ACCEL - 0.01), ENTER_LAT_ACCEL - 0.01)
  weights = run(helper, wander)
  assert not helper.in_curve
  assert (weights == 0.0).all()


@pytest.mark.parametrize("sign", (1, -1))
def test_a_curve_brings_the_weight_in_and_keeps_it(sign):
  helper = CurveWeight(DT)
  before = run(helper, sign * ramp(0.0, ENTER_LAT_ACCEL - 0.01, 0.6))
  assert (before == 0.0).all()                 # not a curve yet
  run(helper, sign * ramp(ENTER_LAT_ACCEL - 0.01, 1.5, 0.6))
  assert helper.in_curve
  held = run(helper, sign * hold(1.5, 3.0))
  assert held[-1] > 0.999
  eased = run(helper, sign * ramp(1.5, LEAVE_LAT_ACCEL + 0.1, 0.6))
  assert eased.min() > 0.999                   # easing the curve is still the curve


def test_leaves_the_curve_only_after_the_request_has_settled_near_straight():
  helper = CurveWeight(DT)
  run(helper, ramp(0.0, 1.2, 0.6))
  run(helper, ramp(1.2, LEAVE_LAT_ACCEL + 0.1, 0.6))
  run(helper, hold(LEAVE_LAT_ACCEL + 0.1, 3.0))
  assert helper.in_curve                       # still a gentle curve

  run(helper, ramp(LEAVE_LAT_ACCEL + 0.1, 0.0, 0.6))
  assert helper.in_curve                       # only just arrived
  leaving = run(helper, hold(0.0, LEAVE_HOLD_S + 1.5))
  assert not helper.in_curve
  after = run(helper, hold(0.0, 8 * LEAVE_TAU_S))
  assert (np.diff(np.r_[leaving, after]) <= 1e-12).all()   # it only goes down
  assert after[-1] == 0.0                      # and ends at exactly nothing, not a small remainder
  assert (run(helper, hold(0.0, 5.0)) == 0.0).all()


def test_a_request_that_is_still_moving_does_not_end_the_curve():
  helper = CurveWeight(DT)
  run(helper, ramp(0.0, 1.2, 0.8))
  t = np.arange(0.0, 6.0, DT)
  swaying = 0.25 * np.sin(2 * np.pi * 1.0 * t)  # inside the leave level, but swinging through it once a second
  weights = run(helper, np.r_[ramp(1.2, 0.0, 0.8), swaying])
  assert helper.in_curve
  assert weights.min() > 0.9


def test_stays_in_the_curve_through_an_s_bend():
  helper = CurveWeight(DT)
  run(helper, ramp(0.0, 1.2, 0.8))
  weights = run(helper, ramp(1.2, -1.2, 0.8))
  assert helper.in_curve
  assert weights.min() > 0.9                   # never let go on the way through zero


def test_the_weight_never_steps():
  rng = np.random.default_rng(1)
  helper = CurveWeight(DT)
  profile = np.r_[ramp(0.0, 2.0, 1.5), hold(2.0, 1.0), ramp(2.0, -2.5, 4.0), ramp(-2.5, 0.0, 2.0), hold(0.0, 9.0)]
  profile = profile + rng.normal(0.0, 0.02, len(profile))
  weights = run(helper, np.r_[profile, 3.0, 3.0])   # ends with a request that jumps straight into a curve
  assert np.abs(np.diff(np.r_[0.0, weights])).max() <= DT / min(ENTER_TAU_S, LEAVE_TAU_S) + 1e-12
  assert weights.min() >= 0.0 and weights.max() <= 1.0


def test_a_request_that_is_not_a_number_changes_nothing():
  helper = CurveWeight(DT)
  run(helper, ramp(0.0, 1.5, 0.6))
  weight = helper.weight
  assert run(helper, [float("nan"), float("inf")]).tolist() == [weight, weight]
  reference = CurveWeight(DT)
  run(reference, ramp(0.0, 1.5, 0.6))
  more = hold(1.5, 1.0)
  assert (run(helper, more) == run(reference, more)).all()


def test_reset_forgets_everything():
  helper = CurveWeight(DT)
  run(helper, ramp(0.0, 2.0, 1.0))
  helper.reset()
  assert (helper.weight, helper.in_curve) == (0.0, False)
  fresh = CurveWeight(DT)
  again = np.r_[ramp(0.0, 0.5, 0.3), ramp(0.5, 1.5, 0.6)]
  assert (run(helper, again) == run(fresh, again)).all()
