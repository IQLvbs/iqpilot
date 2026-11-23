import numpy as np
import pytest

from iqpilot.selfdrive.controls.lib.smooth_stops import SMOOTH_STOP_MAX_SPEED
from iqpilot.selfdrive.controls.lib.stop_point import (
  ARM_SPEED,
  CAP_JERK,
  CONFIRM_TIME,
  CREEP_EXTRA_MAX,
  CREEP_V,
  DROP_TIME,
  FREEZE_SPEED,
  GAS_LOCKOUT,
  GO_TIME,
  LAND_DECEL_MAX,
  LAND_DROP_SPEED,
  LAND_DROP_TIME,
  LEAD_ROOM,
  REST_HOLD_TIME,
  StopPoint,
  landing_distance,
  plan_stop_distance,
)

DT = 0.05
CREEP = 0.4          # m/s^2 this car brakes less than asked at walking pace (measured Nov 7-13: 0.4 typical, up to 0.8)
MOST_ASKED = LAND_DECEL_MAX + max(CREEP_V) + CREEP_EXTRA_MAX


def creep_at(v, creep):
  """How much less than asked the car brakes at speed v (the measured shape, scaled to `creep` at walking pace)."""
  return creep * float(np.interp(v, [0.3, 0.7, 2.0, 3.0], [1.0, 0.875, 0.625, 0.25]))


class Road:
  """A car on the way to a stop line, as the logs show it: the model brakes for a point, at a crawl its point drifts
  ahead of the car, and at walking pace the car brakes less than it is asked to (idle creep)."""
  def __init__(self, v=12.0, line=60.0, helper=True, creep=CREEP):
    self.v, self.a, self.x, self.line, self.creep = v, 0.0, 0.0, line, creep
    self.helper = StopPoint(DT) if helper else None
    self.out, self.stop = 0.0, False
    self.hold = False                                                  # the speed controller's hold once a stop is complete
    self.stops, self.outs, self.plans = [], [], []

  def model(self):
    """(plan stop distance, plan top speed, model accel): a steady stop at the line; drifting ahead when slow"""
    room = self.line - self.x
    if self.v < FREEZE_SPEED:
      return max(room, 1.0), self.v, -0.2
    return max(room, 0.5), self.v, -min(self.v ** 2 / (2.0 * max(room, 0.5)), 2.5)

  def step(self, gas=False, active=True, lead=None, model=None):
    plan_d, top, a_model = model if model is not None else self.model()
    a_plan = a_model
    self.plans.append(a_plan)
    if self.helper is not None:
      self.out, self.stop = self.helper.update(a_plan, self.out, active, self.v, self.v < 0.02, gas, plan_d, top, a_model, lead, a_ego=self.a)
    else:
      self.out, self.stop = a_plan, False
    self.stops.append(self.stop)
    self.outs.append(self.out)
    if self.stop and self.v <= SMOOTH_STOP_MAX_SPEED:
      cmd = min(self.out, -(0.25 + 0.55 * min(self.v, 1.0)))          # the speed controller's soft stop
    else:
      cmd = self.out
    got = cmd + creep_at(self.v, self.creep) + (0.2 if self.v < 1.0 and not self.stop else 0.0)   # idle creep; rolls on at a crawl
    self.a += (got - self.a) * DT / 0.2
    self.v = max(0.0, self.v + self.a * DT)
    self.hold = (self.hold or (self.stop and self.v <= 0.05)) and a_plan <= 0.3
    if self.hold:
      self.v = self.a = 0.0
    self.x += self.v * DT

  def drive(self, seconds, **kw):
    for _ in range(int(seconds / DT)):
      self.step(**kw)
    return self


def test_plan_stop_distance_reads_where_the_plan_comes_to_rest():
  assert plan_stop_distance([0, 5, 9, 11, 11.5], [8, 5, 2, 0.2, 0]) == pytest.approx(9 + (2 - 0.3) / (2 - 0.2) * 2)
  assert plan_stop_distance([0, 5, 10], [8, 8, 8]) is None
  assert plan_stop_distance([0, 1, 2], [0.1, 0.0, 0.0]) == 0.0
  assert plan_stop_distance([], []) is None
  assert plan_stop_distance([0, 5], [8, 5, 0]) is None                 # lengths differ: only the common part is read
  assert plan_stop_distance([0, float('nan')], [8, 0]) is None


def test_landing_distance_matches_the_soft_stop_profile():
  d = [landing_distance(v) for v in np.linspace(0.0, 3.0, 31)]
  assert d[0] == 0.0 and all(np.diff(d) > 0)
  assert landing_distance(1.0) == pytest.approx(0.857 + 0.3, abs=0.01)
  assert landing_distance(3.0) == pytest.approx(0.857 + 8.0 / 1.6 + 0.9, abs=0.01)


def test_it_never_asks_for_more_than_the_plan_and_changes_nothing_before_the_landing():
  rng = np.random.default_rng(3)
  helper = StopPoint(DT)
  out = 0.0
  for _ in range(6000):
    target = float(rng.uniform(-3.0, 2.0))
    v = float(rng.uniform(0.0, 20.0))
    plan = float(rng.uniform(0.0, 60.0)) if rng.random() < 0.6 else None
    lead = float(rng.uniform(0.0, 80.0)) if rng.random() < 0.1 else None
    out, stop = helper.update(target, out, bool(rng.random() < 0.95), v, v < 0.02, bool(rng.random() < 0.01), plan, float(rng.uniform(0.0, 20.0)),
                              float(rng.uniform(-2.0, 1.5)), lead, a_ego=float(rng.uniform(-3.0, 2.0)))
    assert out <= target
    assert out >= min(target, -MOST_ASKED) - 1e-9                       # never more braking than the landing's ceiling
    if not stop:
      assert out == target
    if v > SMOOTH_STOP_MAX_SPEED and not helper.finishing:
      assert not stop


def test_without_it_the_car_crawls_past_the_point():
  without = Road(helper=False).drive(40.0)
  assert without.x > without.line + 1.5 or without.v > 0.1             # the logged behaviour: it keeps rolling


def test_with_the_strongest_creep_seen_it_still_ends_the_crawl():
  road = Road(creep=0.8).drive(40.0)                                    # the worst seen: twice the typical shortfall
  assert road.v == 0.0 and road.x - road.line < 1.5                     # stopped, well short of where it used to


@pytest.mark.parametrize("creep", [0.0, 0.2, 0.4])
def test_the_car_stops_at_the_point_however_much_it_creeps(creep):
  road = Road(creep=creep).drive(40.0)
  assert road.v == 0.0
  assert -0.8 < road.x - road.line < 0.6                                # at the point, not 2 m past it
  first = road.stops.index(True)
  rest = next(k for k in range(first, len(road.stops)) if not road.stops[k])
  assert (rest - first) * DT < 8.0                                      # landing and the hold at rest, then it hands back
  assert not any(road.stops[rest:])                                     # and stays out of it afterwards
  landing = np.array(road.outs[first:rest])
  assert landing.min() >= -MOST_ASKED - 1e-6
  assert np.diff(landing).min() >= -CAP_JERK * DT - 1e-9                # the request deepens gently


def test_the_braking_on_the_way_in_is_untouched():
  road = Road()
  while road.v > SMOOTH_STOP_MAX_SPEED + 0.05:
    road.step()
    assert road.out == road.plans[-1] and not road.stop


def test_a_single_frame_of_a_stopping_plan_is_not_taken():
  helper = StopPoint(DT)
  for k in range(40):
    helper.update(0.0, 0.0, True, 10.0, False, False, 30.0 if k % 5 == 0 else None, 10.0, 0.0, None)
    assert helper.point is None
  for _ in range(int(CONFIRM_TIME / DT) + 1):
    helper.update(0.0, 0.0, True, 10.0, False, False, 30.0, 10.0, 0.0, None)
  assert helper.point is not None


def test_the_point_is_given_up_when_the_plan_no_longer_stops():
  road = Road().drive(2.0)
  assert road.helper.point is not None
  for _ in range(int(DROP_TIME / DT) + 2):
    road.step(model=(None, 12.0, 0.5))                                  # the light changed
    assert road.out == 0.5 and not road.stop
  assert road.helper.point is None


def test_the_point_does_not_move_once_the_car_is_slow():
  road = Road()
  while road.v >= FREEZE_SPEED:
    road.step()
  point = road.helper.point
  for _ in range(10):
    road.step(model=(25.0, road.v, -0.2))                               # the model's point jumps far ahead at a crawl
  assert road.helper.point == point


def test_a_green_light_during_the_landing_releases_it():
  road = Road()
  while not road.stop:
    road.step()
  for _ in range(4):
    road.step(model=(None, road.v, 0.8))                                # asks for acceleration but its plan does not pick up speed
    assert road.stop
  for _ in range(int(GO_TIME / DT) + 2):
    road.step(model=(None, 8.0, 0.8))
  assert not road.stop and road.out == 0.8 and road.helper.point is None


def test_the_stop_is_held_for_a_moment_at_rest_and_then_handed_back():
  road = Road()
  while road.v > 0.0:
    road.step()
  held = 0
  while road.stop:
    road.step()
    held += 1
    assert road.out == road.plans[-1]                                   # at rest the request itself is the plan's
  assert REST_HOLD_TIME - 0.5 < held * DT <= REST_HOLD_TIME + DT
  assert not road.helper.armed
  road.drive(5.0)
  assert not any(road.stops[-50:]) and road.v == 0.0                    # handed back; the hold keeps the car


def test_a_creep_from_rest_is_never_touched():
  helper = StopPoint(DT)
  v = 0.0
  for _ in range(400):
    v = min(ARM_SPEED - 0.5, v + 0.5 * DT)
    out, stop = helper.update(0.4, 0.4, True, v, v < 0.02, False, 1.5, v, 0.4, None)
    assert out == 0.4 and not stop and helper.point is None


def test_the_accelerator_releases_it_and_keeps_it_out_for_a_while():
  road = Road().drive(2.0)
  assert road.helper.point is not None
  road.step(gas=True)
  assert road.helper.point is None and not road.stop
  for _ in range(int(GAS_LOCKOUT / DT) - 2):
    road.step(model=(20.0, 8.0, -1.0))
    assert road.helper.point is None and road.out == -1.0
  road.drive(1.0)
  assert road.helper.point is not None or road.v < FREEZE_SPEED


def test_cruise_not_in_control_releases_it():
  road = Road()
  while not road.stop:
    road.step()
  road.step(active=False)
  assert not road.stop and road.helper.point is None and road.out == road.plans[-1]


def test_a_car_ahead_close_to_the_point_owns_the_stop():
  road = Road().drive(2.0)
  room = road.helper.remaining
  road.step(lead=room + LEAD_ROOM + 5.0)
  assert road.helper.point is not None                                  # far beyond the point: ignored
  road.step(lead=room + LEAD_ROOM - 1.0)
  assert road.helper.point is None and not road.stop


def test_a_car_that_arrives_too_fast_is_not_braked_hard():
  helper = StopPoint(DT)
  for _ in range(20):
    helper.update(-1.0, -1.0, True, 6.0, False, False, 3.0, 6.0, -1.0, None)   # arms and takes a point 3 m ahead at 6 m/s
  out, outs, v = -1.0, [], 3.0
  for _ in range(60):
    out, stop = helper.update(-0.2, out, True, v, False, False, 1.0, v, -0.2, None)
    assert stop
    outs.append(out)
    v = max(v + out * DT, 0.2)
  outs = np.array(outs)
  assert outs.min() >= -MOST_ASKED - 1e-9
  assert np.diff(np.r_[-1.0, outs]).min() >= -CAP_JERK * DT - 1e-9


def landing_helper(v=2.5, room=4.0):
  """A helper that has armed, taken a point `room` ahead and started its landing at speed v."""
  helper = StopPoint(DT)
  for _ in range(20):
    helper.update(-0.5, -0.5, True, 6.0, False, False, 20.0, 6.0, -0.5, None)
  helper.point = helper.odometer + room
  out, stop = helper.update(-0.5, -0.5, True, v, False, False, room, v, -0.5, None)
  assert stop and helper.finishing
  return helper


def test_the_landing_asks_for_more_while_the_car_still_creeps():
  helper = landing_helper(v=1.0, room=1.0)
  out, outs = -0.5, []
  for _ in range(40):                                                   # the car is not slowing at all (a_ego 0)
    out, stop = helper.update(-0.2, out, True, 1.0, False, False, 2.0, 1.0, -0.2, None, a_ego=0.0)
    assert stop
    outs.append(out)
  assert helper.extra == pytest.approx(CREEP_EXTRA_MAX)                 # it learnt the car needs more, up to its limit
  assert outs[-1] < outs[0] - 0.3
  steady = landing_helper(v=1.0, room=1.0)
  for _ in range(40):                                                   # the car slows as aimed for: nothing extra
    steady.update(-0.2, -1.5, True, 1.0, False, False, 2.0, 1.0, -0.2, None, a_ego=-1.5)
  assert steady.extra == 0.0


def test_a_slow_down_that_is_not_a_stop_is_given_up():
  helper = landing_helper(v=1.5, room=1.8)
  steps = int(round(LAND_DROP_TIME / DT))
  for _ in range(steps - 1):                                            # the model's plan stops coming to rest ...
    out, stop = helper.update(-0.3, -0.5, True, 1.5, False, False, None, 2.0, -0.3, None, a_ego=-0.4)
    assert stop
  out, stop = helper.update(-0.3, -0.5, True, 1.5, False, False, None, 2.0, -0.3, None, a_ego=-0.4)
  assert not stop and out == -0.3 and helper.point is None and not helper.armed   # ... for 0.7 s: it goes on


def test_a_short_gap_in_the_plan_does_not_end_a_landing():
  helper = landing_helper(v=1.5, room=1.8)
  for k in range(60):                                                   # 0.45 s gaps, as seen in real stops
    plan = None if k % 12 < 9 else 2.0
    out, stop = helper.update(-0.3, -0.5, True, 1.5, False, False, plan, 1.5, -0.3, None, a_ego=-0.4)
    assert stop


def test_near_rest_a_landing_is_never_given_up_for_a_missing_plan():
  helper = landing_helper(v=LAND_DROP_SPEED - 0.1, room=0.5)
  for _ in range(int(2.0 / DT)):
    out, stop = helper.update(-0.2, -0.5, True, LAND_DROP_SPEED - 0.1, False, False, None, 0.3, -0.2, None, a_ego=-0.3)
    assert stop
