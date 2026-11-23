import math

import numpy as np

from iqpilot.selfdrive.controls.lib.smooth_stops import SETTLE_DECEL, SMOOTH_STOP_MAX_SPEED, STANDSTILL_SPEED, STOP_KISS_DECEL, TAPER_SPEED

STOP_POINT_FINGERPRINTS = frozenset({"HYUNDAI_TUCSON_4TH_GEN"})

STOP_MARGIN = 0.0          # m before the remembered point
ARM_SPEED = 5.0            # m/s the car must have reached since it last stood still; a creep from rest is never touched
FREEZE_SPEED = 2.5         # m/s: below this the model's point follows the car, so the remembered one is kept
CONFIRM_TIME = 0.3         # s the plan must come to rest before the point is taken
POINT_TAU = 0.5            # s
DROP_TIME = 0.6            # s without a stop in the plan before the point is given up
GO_ACCEL = 0.3             # m/s^2 asked by the model, with a plan reaching GO_PLAN_SPEED, for GO_TIME: it wants to go again
GO_PLAN_SPEED = 2.0        # m/s
GO_TIME = 0.5              # s
REST_SPEED = 0.1           # m/s
REST_HOLD_TIME = 1.0       # s the stop is still asked for at rest; after that the usual logic owns it
GAS_LOCKOUT = 5.0          # s after the accelerator before a new point is taken
LEAD_ROOM = 8.0            # m: a car tracked closer than the point plus this owns the stop
PLAN_REST_SPEED = 0.3      # m/s: the plan comes to rest where it first falls below this
CAP_JERK = 2.0             # m/s^3

# the landing: a steady stop at the point, plus the braking the car leaves out at walking pace (idle creep)
LAND_DECEL_MIN = 0.25      # m/s^2
LAND_DECEL_MAX = 1.5       # m/s^2: a car that arrives faster than this rolls a little past the point
LAND_MIN_ROOM = 0.5        # m
CREEP_SPEED_BP = [0.3, 0.7, 2.0, 3.0]  # m/s
CREEP_V = [0.40, 0.35, 0.25, 0.10]     # m/s^2 less than asked, typically
CREEP_GAIN = 2.0           # 1/s: how fast the extra request grows while the car still brakes less than aimed for
CREEP_EXTRA_MAX = 0.8      # m/s^2
CREEP_EXTRA_MIN = 0.0
CREEP_LEARN_SPEED = 0.15   # m/s
A_EGO_TAU = 0.15           # s
LAND_DROP_TIME = 0.7       # s without the plan coming to rest, while still moving, before a landing is given up
LAND_DROP_SPEED = 0.5      # m/s
FEATHER_SPEED_BP = [0.35, 0.7]  # m/s
FEATHER_V = [0.3, 0.0]          # m: aim this much further at the very end, so the car settles rather than halts
LANDING_DELAY = 0.3        # s of travel before the brake answers
LANDING_SLACK = 0.2        # m


def uses_stop_point(cp) -> bool:
  return str(cp.carFingerprint) in STOP_POINT_FINGERPRINTS


def plan_stop_distance(position_x, velocity_x) -> float | None:
  """Distance along the driving model's plan to where it comes to rest, None if it does not."""
  for k in range(min(len(position_x), len(velocity_x))):
    v = float(velocity_x[k])
    if v < PLAN_REST_SPEED:
      if k == 0:
        return 0.0
      v_before = float(velocity_x[k - 1])
      share = (v_before - PLAN_REST_SPEED) / (v_before - v) if v_before > v else 1.0
      x = float(position_x[k - 1]) + share * (float(position_x[k]) - float(position_x[k - 1]))
      return max(x, 0.0) if math.isfinite(x) else None
  return None


def landing_distance(v: float) -> float:
  """Road the soft stop needs from speed v, with the brake's delay."""
  v = max(float(v), 0.0)
  slope = (SETTLE_DECEL - STOP_KISS_DECEL) / TAPER_SPEED
  low = min(v, TAPER_SPEED)
  taper = low / slope - (STOP_KISS_DECEL / slope ** 2) * math.log(1.0 + slope * low / STOP_KISS_DECEL)
  steady = (v ** 2 - TAPER_SPEED ** 2) / (2.0 * SETTLE_DECEL) if v > TAPER_SPEED else 0.0
  return taper + steady + LANDING_DELAY * v


class StopPoint:
  """Finishes a stop at a light or sign where the driving model planned it on the way in.
  Only ever lowers the acceleration and adds a stop request; never moves a stop for a car ahead."""

  def __init__(self, dt: float):
    self.dt = dt
    self.odometer = 0.0  # m travelled, the road coordinate
    self.armed = False
    self.lockout = 0.0
    self.release()

  def release(self, disarm: bool = False) -> None:
    self.point = None    # road coordinate of the remembered stopping point
    self.seen_for = 0.0
    self.missing_for = 0.0
    self.go_for = 0.0
    self.rest_for = 0.0
    self.finishing = False
    self.extra = 0.0     # m/s^2 on top of the typical shortfall, learnt during this landing
    self.a_ego = None
    self.land_missing = 0.0
    if disarm:
      self.armed = False

  @property
  def remaining(self) -> float | None:
    return None if self.point is None else self.point - STOP_MARGIN - self.odometer

  def update(self, a_target: float, a_prev: float, active: bool, v_ego: float, standstill: bool, gas: bool,
             plan_distance: float | None, plan_top_speed: float, model_accel: float,
             lead_distance: float | None, a_ego: float | None = None) -> tuple[float, bool]:
    """Returns the acceleration to ask for (never above a_target) and whether to ask for the stop."""
    v_ego = max(float(v_ego), 0.0)
    self.odometer += v_ego * self.dt
    self.lockout = max(self.lockout - self.dt, 0.0)
    at_rest = standstill or v_ego < REST_SPEED

    if gas:
      self.lockout = GAS_LOCKOUT
    if not active or gas:
      self.release(disarm=at_rest)
      return a_target, False
    if at_rest and not self.finishing:
      self.release(disarm=True)
      return a_target, False
    if v_ego > ARM_SPEED:
      self.armed = True
    if not self.armed or self.lockout > 0.0:
      self.release()
      return a_target, False

    planned = plan_distance is not None and math.isfinite(plan_distance)
    if self.point is not None and (self.finishing or v_ego < FREEZE_SPEED):
      # slow, landing or held at rest: the point is kept; only the model wanting to go again gives it up
      wants_to_go = model_accel > GO_ACCEL and plan_top_speed > GO_PLAN_SPEED
      self.go_for = self.go_for + self.dt if wants_to_go else 0.0
      if self.go_for > GO_TIME:
        self.release(disarm=True)
    elif v_ego >= FREEZE_SPEED:
      if planned:
        self.missing_for = 0.0
        self.seen_for += self.dt
        candidate = self.odometer + float(plan_distance)
        if self.point is None:
          if self.seen_for >= CONFIRM_TIME:
            self.point = candidate
        else:
          self.point += (candidate - self.point) * self.dt / (POINT_TAU + self.dt)
      else:
        self.seen_for = 0.0
        self.missing_for += self.dt
        if self.missing_for > DROP_TIME:
          self.release()

    if self.point is None:
      return a_target, False

    room = self.remaining
    if lead_distance is not None and lead_distance < max(room, 0.0) + LEAD_ROOM:
      self.release(disarm=at_rest)
      return a_target, False

    if v_ego <= SMOOTH_STOP_MAX_SPEED and room <= landing_distance(v_ego) + LANDING_SLACK:
      self.finishing = True
    if not self.finishing:
      return a_target, False
    if v_ego > LAND_DROP_SPEED:
      self.land_missing = 0.0 if planned else self.land_missing + self.dt
      if self.land_missing >= LAND_DROP_TIME:
        # the model slowed for something and goes on: do not turn that into a stop
        self.release(disarm=True)
        return a_target, False
    if standstill or v_ego <= STANDSTILL_SPEED:
      # the stop is complete: keep asking for a moment so the hold settles, then hand back
      self.rest_for += self.dt
      if self.rest_for > REST_HOLD_TIME:
        self.release(disarm=True)
        return a_target, False
      return a_target, True
    self.rest_for = 0.0

    room_aim = max(room, LAND_MIN_ROOM) + float(np.interp(v_ego, FEATHER_SPEED_BP, FEATHER_V))
    soft = STOP_KISS_DECEL + (SETTLE_DECEL - STOP_KISS_DECEL) * min(v_ego / TAPER_SPEED, 1.0)  # never gentler than the soft stop
    aim = min(max(v_ego ** 2 / (2.0 * room_aim), soft, LAND_DECEL_MIN), LAND_DECEL_MAX)
    if a_ego is not None and math.isfinite(a_ego):
      a_now = float(a_ego)
      self.a_ego = a_now if self.a_ego is None else self.a_ego + (a_now - self.a_ego) * self.dt / (A_EGO_TAU + self.dt)
      if v_ego > CREEP_LEARN_SPEED:
        short = self.a_ego + aim  # > 0: the car is braking less than aimed for
        self.extra = float(np.clip(self.extra + CREEP_GAIN * short * self.dt, CREEP_EXTRA_MIN, CREEP_EXTRA_MAX))
    shortfall = max(float(np.interp(v_ego, CREEP_SPEED_BP, CREEP_V)) + self.extra, 0.0)
    target = max(-(aim + shortfall), a_prev - CAP_JERK * self.dt)
    return float(min(a_target, target)), True
