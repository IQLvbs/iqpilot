"""Keeps a tapped turn signal on through the lane change it asks for, then lets it go.

A tap gives the car's own three flashes (about 2 s); a lane change takes about 5 s after the nudge. Where the car can be
asked to hold a signal, this asks for the driver's side from the moment the lamp comes on until the lane change is done.
Only the lamp feedback is read, and only a lamp coming on starts a hold, so its own blink never does."""
from iqdbc.car.hyundai.values import HyundaiFlags
from iqpilot.cereal import log
from iqpilot.common.realtime import DT_CTRL

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection

LANE_CHANGE_SPEED = 20 * 0.44704  # m/s: 20 mph, where the lane change logic starts offering lane changes
GRACE = 2.0         # s for the lane change logic to show a lane change in that direction
WAIT_MAX = 10.0     # s of waiting for the nudge
AGAINST_TIME = 1.0  # s of steering the other way while it waits, to cancel
HOLD_MAX = 20.0     # s in all, whatever the lane change logic says
NAV_QUIET = 1.0     # s after a navigation request during which a lamp coming on is not taken as the driver's

NONE, LEFT, RIGHT = 0, 1, 2


def holds_lane_change_signal(CP) -> bool:
  return CP.brand == "hyundai" and bool(CP.flags & HyundaiFlags.CANFD_SPAS2_BLINKERS)


def _raw(value):
  return getattr(value, "raw", value)


class LaneChangeSignal:
  def __init__(self, enabled: bool):
    self.enabled = bool(enabled)
    self.side = NONE
    self.prev_left = self.prev_right = True   # a lamp already on at start-up is not a new signal
    self.nav_quiet = 0.0
    self._clear()

  def _clear(self):
    self.side = NONE
    self.time = 0.0
    self.waiting = 0.0
    self.against = 0.0
    self.seen = False
    self.changing = False

  def update(self, lane_change_state, lane_change_direction, left_lamp: bool, right_lamp: bool, v_ego: float,
             lat_active: bool, steering_pressed: bool, steering_torque: float, nav_left: bool, nav_right: bool) -> tuple[bool, bool]:
    """One controlsd frame. Returns (left, right): the signal to ask for, on top of what navigation asks for."""
    if not self.enabled:
      return False, False
    state, direction = _raw(lane_change_state), _raw(lane_change_direction)
    left_lamp, right_lamp = bool(left_lamp), bool(right_lamp)
    rose_left, rose_right = left_lamp and not self.prev_left, right_lamp and not self.prev_right
    self.prev_left, self.prev_right = left_lamp, right_lamp
    self.nav_quiet = NAV_QUIET if (nav_left or nav_right) else max(0.0, self.nav_quiet - DT_CTRL)

    if self.side != NONE and self._done(state, direction, left_lamp, right_lamp, lat_active, steering_pressed, steering_torque,
                                        nav_left, nav_right):
      # a signal that ends this one (the other side, the hazards) stays the driver's own: no new hold on the same frame
      self._clear()
      return False, False

    if self.side == NONE and lat_active and v_ego >= LANE_CHANGE_SPEED and self.nav_quiet == 0.0 and not (left_lamp and right_lamp):
      if rose_left:
        self.side = LEFT
      elif rose_right:
        self.side = RIGHT
    return self.side == LEFT, self.side == RIGHT

  def _done(self, state, direction, left_lamp, right_lamp, lat_active, steering_pressed, steering_torque, nav_left, nav_right) -> bool:
    self.time += DT_CTRL
    left = self.side == LEFT
    other_lamp, other_nav = (right_lamp, nav_right) if left else (left_lamp, nav_left)
    if not lat_active or other_lamp or other_nav or self.time > HOLD_MAX:
      return True
    wanted = LaneChangeDirection.left if left else LaneChangeDirection.right
    if direction == wanted and state in (LaneChangeState.preLaneChange, LaneChangeState.laneChangeStarting,
                                         LaneChangeState.laneChangeFinishing):
      self.seen = True
      if state == LaneChangeState.laneChangeFinishing:
        # in the new lane: let go now, so the lamps are out before the logic could take a push on the wheel as a new nudge
        return True
      if state != LaneChangeState.preLaneChange:
        self.changing = True
        return False
      if self.changing:
        return True                     # waiting again after a lane change: that one is done
      self.waiting += DT_CTRL
      # steering torque is + to the left on this car
      pushing_back = steering_pressed and (steering_torque < 0.0 if left else steering_torque > 0.0)
      self.against = self.against + DT_CTRL if pushing_back else 0.0
      return self.against >= AGAINST_TIME or self.waiting > WAIT_MAX
    # off, or another direction: done once a lane change was under way, or if none came within GRACE
    return self.seen or self.time > GRACE
