from typing import NamedTuple

import numpy as np

from iqpilot.common.filter_simple import FirstOrderFilter

SPEED_COMFORT_FINGERPRINTS = frozenset({"HYUNDAI_TUCSON_4TH_GEN"})


class CruiseShape(NamedTuple):
  gain_above: float  # 1/s: acceleration asked per m/s above the target (stock 1.0)
  gain_below: float  # 1/s: per m/s below it (stock 1.0)
  min_accel: float   # m/s^2
  jerk_brake: float  # m/s^3: how fast braking may build


RETURN_SHAPE = CruiseShape(gain_above=0.3, gain_below=0.5, min_accel=-0.8, jerk_brake=0.5)  # back down to the set speed
BEND_SHAPE = CruiseShape(gain_above=0.5, gain_below=0.5, min_accel=-0.8, jerk_brake=0.6)    # down to the camera's bend target


def uses_speed_comfort(cp) -> bool:
  return str(cp.carFingerprint) in SPEED_COMFORT_FINGERPRINTS


def cruise_shape(source_is_nav: bool, nav_provider, forced: bool) -> CruiseShape | None:
  if forced:
    return None
  if source_is_nav:
    return BEND_SHAPE if str(nav_provider) == "vision" else None
  return RETURN_SHAPE

# picking the drive back up: how far the request may run ahead of the acceleration the car is delivering
PICKUP_MARGIN = 0.35              # m/s^2
PICKUP_JERK = 0.8                 # m/s^3
PICKUP_PATIENCE = 0.25            # m/s^2 more per second held back, so a car that does not answer still gets the request
PICKUP_A_EGO_TAU = 0.3            # s
TAKEOVER_TIME = 2.5               # s after cruise takes over while moving
TAKEOVER_MIN_SPEED = 2.0          # m/s: below this a take-over is a launch and is left alone
BACKOFF_ACCEL = 0.5               # m/s^2: below this the plan had backed off
BACKOFF_MIN_SPEED = 2.5           # m/s
BACKOFF_TIME = 1.5                # s
BACKOFF_SPEED_BP = [8.0, 11.0]    # m/s: in full below 18 mph, gone by 25 mph
BACKOFF_SPEED_V = [1.0, 0.0]
BACKOFF_BEND_LAT_BP = [1.0, 2.0]  # m/s^2 lateral: in a bend it acts at any speed
BACKOFF_BEND_V = [0.0, 1.0]

# the planned speed may lead a car that has not picked up the drive by this much
RUN_AHEAD_MARGIN = 0.1            # m/s
RUN_AHEAD_MIN_ASK = 0.2           # m/s^2
RUN_AHEAD_SHORT = 0.3             # m/s^2 short of the ask counts as not answering
RUN_AHEAD_TIME = 1.5              # s, then the margin opens at RUN_AHEAD_OPEN so a car on a hill still gets the loop's help
RUN_AHEAD_OPEN = 0.5              # m/s per s

# acceleration allowed while cornering, by lateral acceleration from the wheel angle
TURN_LAT_ACCEL_BP = [1.0, 2.0]
TURN_ACCEL_V = [2.0, 1.0]


class PickupLimiter:
  """Keeps the request and the planned speed from running ahead of a car that is still picking the drive back up.
  Only ever lowers a positive acceleration."""

  def __init__(self, dt: float):
    self.dt = dt
    self.window = 0.0     # s left in which the pick-up cap applies
    self.takeover = False
    self.held_for = 0.0   # s the cap has held the request back without a break
    self.a_ego = FirstOrderFilter(0.0, PICKUP_A_EGO_TAU, dt, initialized=False)
    self.run_ahead_for = 0.0
    self.a_ego_run_ahead = FirstOrderFilter(0.0, PICKUP_A_EGO_TAU, dt, initialized=False)

  def limit_rise(self, a_target: float, a_prev: float, reset_state: bool, v_ego: float, a_ego: float, lateral_accel: float,
                 standstill: bool) -> float:
    delivered = self.a_ego.update(a_ego)
    if reset_state:
      self.takeover = v_ego > TAKEOVER_MIN_SPEED
      self.window = TAKEOVER_TIME if self.takeover else 0.0
      self.held_for = 0.0
      return a_target

    cap = float(np.interp(abs(lateral_accel), TURN_LAT_ACCEL_BP, TURN_ACCEL_V))

    if a_prev < BACKOFF_ACCEL and v_ego > BACKOFF_MIN_SPEED and not standstill:
      self.window = max(self.window, BACKOFF_TIME)
    if self.window > 0.0:
      weight = 1.0 if self.takeover else max(float(np.interp(v_ego, BACKOFF_SPEED_BP, BACKOFF_SPEED_V)),
                                             float(np.interp(abs(lateral_accel), BACKOFF_BEND_LAT_BP, BACKOFF_BEND_V)))
      pickup = min(max(delivered, 0.0) + PICKUP_MARGIN + PICKUP_PATIENCE * self.held_for, max(a_prev, 0.0) + PICKUP_JERK * self.dt)
      holding = weight > 0.0 and a_target > pickup
      self.held_for = self.held_for + self.dt if holding else 0.0
      # never let go with a step: a window that is still holding the request back stays open until the request has caught up
      self.window = max(self.window - self.dt, self.dt if holding else 0.0)
      if self.window <= 0.0:
        self.takeover = False
      if holding:
        cap = min(cap, pickup + (1.0 - weight) * (a_target - pickup))

    return min(a_target, max(cap, 0.0))

  def limit_run_ahead(self, v_desired: float, v_ego: float, a_asked: float, a_ego: float, reset_state: bool) -> float:
    delivered = self.a_ego_run_ahead.update(a_ego)
    if reset_state:
      self.run_ahead_for = 0.0
      return v_desired
    short = a_asked > RUN_AHEAD_MIN_ASK and delivered < a_asked - RUN_AHEAD_SHORT
    self.run_ahead_for = self.run_ahead_for + self.dt if short else 0.0
    if not short:
      return v_desired
    margin = RUN_AHEAD_MARGIN + RUN_AHEAD_OPEN * max(0.0, self.run_ahead_for - RUN_AHEAD_TIME)
    return min(v_desired, v_ego + margin)
