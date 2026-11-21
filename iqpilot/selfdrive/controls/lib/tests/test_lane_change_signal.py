"""Tests for lane_change_signal.py: a tapped turn signal kept on through the lane change it asks for."""
import pytest

from iqpilot.cereal import log
from iqpilot.selfdrive.controls.lib.lane_change_signal import (AGAINST_TIME, DT_CTRL, GRACE, HOLD_MAX, LANE_CHANGE_SPEED, NAV_QUIET, WAIT_MAX,
                                                              LaneChangeSignal)

S = log.LaneChangeState
D = log.LaneChangeDirection
F = lambda s: int(round(s / DT_CTRL))  # noqa: E731  seconds -> frames
SPEED = LANE_CHANGE_SPEED + 3.0


class Drive:
  """Feeds LaneChangeSignal one controlsd frame at a time, the way controlsd does."""

  def __init__(self, enabled=True):
    self.lcs = LaneChangeSignal(enabled)
    self.out = (False, False)
    self.step(1)   # a first frame with everything off

  def step(self, frames, state=S.off, direction=D.none, lamps=(False, False), v=SPEED, lat=True, pressed=False, torque=0.0,
           nav=(False, False)):
    outs = []
    for _ in range(frames):
      self.out = self.lcs.update(state, direction, lamps[0], lamps[1], v, lat, pressed, torque, nav[0], nav[1])
      outs.append(self.out)
    return outs

  def tap(self, side="left", frames=None, **kw):
    """The car's own three flashes: lamp feedback on for about 2 s (CarState holds it between flashes)."""
    lamps = (True, False) if side == "left" else (False, True)
    return self.step(frames or F(2.1), lamps=lamps, **kw)


LEFT_ON, RIGHT_ON, OFF = (True, False), (False, True), (False, False)


def lane_change(d, side="left", wait=0.5, change=3.9, finish=1.0, lamps=None, after=S.off):
  """The lane change logic's states for one lane change, while the lamps show what the car is doing.
  Returns (outputs while waiting and changing, outputs while finishing, output on the frame after)."""
  dirn = D.left if side == "left" else D.right
  lamps = lamps if lamps is not None else (LEFT_ON if side == "left" else RIGHT_ON)
  outs = d.step(F(wait), state=S.preLaneChange, direction=dirn, lamps=lamps)
  outs += d.step(F(change), state=S.laneChangeStarting, direction=dirn, lamps=lamps)
  fin = d.step(F(finish), state=S.laneChangeFinishing, direction=dirn, lamps=lamps)
  end = d.step(1, state=after, direction=dirn if after == S.preLaneChange else D.none, lamps=lamps)
  return outs, fin, end[0]


def test_off_unless_enabled():
  d = Drive(enabled=False)
  assert d.tap() == [(False, False)] * F(2.1)
  outs, fin, end = lane_change(d)
  assert set(outs + fin) == {(False, False)}


def test_a_tap_is_held_through_the_lane_change_and_let_go_as_it_finishes():
  d = Drive()
  first = d.step(1, lamps=LEFT_ON)
  assert first == [(True, False)]                       # held from the first frame the lamps come on
  # the tap's flashes and the waiting for the nudge, then the change: held all the way
  outs, fin, end = lane_change(d, wait=1.5)
  assert set(outs) == {(True, False)}
  # the car is in its new lane: let go on the first frame of finishing, so the lamps are out before it is done
  assert set(fin) == {(False, False)} and end == (False, False)
  # its own blink fading out does not start it again
  assert set(d.step(F(1.0), lamps=LEFT_ON)) == {(False, False)}
  assert set(d.step(F(1.0))) == {(False, False)}


@pytest.mark.parametrize("side", ("left", "right"))
def test_both_sides(side):
  d = Drive()
  lamps = LEFT_ON if side == "left" else RIGHT_ON
  want = (True, False) if side == "left" else (False, True)
  assert d.step(1, lamps=lamps) == [want]
  outs, fin, end = lane_change(d, side=side)
  assert set(outs) == {want} and set(fin) == {(False, False)} and end == (False, False)


def test_a_stalk_pushed_home_is_not_picked_up_again_after_the_change():
  # a stalk pushed home keeps the lamps on: after finishing, the lane change logic waits again
  d = Drive()
  d.step(1, lamps=LEFT_ON)
  outs, fin, end = lane_change(d, after=S.preLaneChange)
  assert set(outs) == {(True, False)} and set(fin) == {(False, False)} and end == (False, False)
  # and it does not pick the held stalk up again while the lamps stay on
  assert set(d.step(F(5), state=S.preLaneChange, direction=D.left, lamps=LEFT_ON)) == {(False, False)}


def test_lets_go_if_the_logic_waits_again_without_finishing():
  d = Drive()
  d.step(1, lamps=LEFT_ON)
  d.step(F(0.3), state=S.preLaneChange, direction=D.left, lamps=LEFT_ON)
  d.step(F(2.0), state=S.laneChangeStarting, direction=D.left, lamps=LEFT_ON)
  assert d.step(1, state=S.preLaneChange, direction=D.left, lamps=LEFT_ON) == [(False, False)]


def test_lets_go_after_grace_when_no_lane_change_shows_up():
  d = Drive()
  outs = d.step(F(GRACE) - 1, lamps=LEFT_ON)
  assert set(outs) == {(True, False)}
  assert d.step(F(0.5), lamps=LEFT_ON)[-1] == (False, False)


def test_lets_go_after_waiting_too_long_for_the_nudge():
  d = Drive()
  d.step(1, lamps=LEFT_ON)
  outs = d.step(F(WAIT_MAX) - 2, state=S.preLaneChange, direction=D.left, lamps=LEFT_ON)
  assert set(outs) == {(True, False)}
  assert d.step(F(0.1), state=S.preLaneChange, direction=D.left, lamps=LEFT_ON)[-1] == (False, False)


def test_steering_the_other_way_for_a_second_while_waiting_cancels_it():
  d = Drive()
  d.step(1, lamps=LEFT_ON)
  d.step(F(0.5), state=S.preLaneChange, direction=D.left, lamps=LEFT_ON)
  # pushing the wheel the same way is the nudge, not a cancel (torque is + to the left)
  assert d.step(F(0.2), state=S.preLaneChange, direction=D.left, lamps=LEFT_ON, pressed=True, torque=+300)[-1] == (True, False)
  # brief pushes the other way, like the 0.6 s ones in his logs, do not cancel
  for _ in range(3):
    outs = d.step(F(0.6), state=S.preLaneChange, direction=D.left, lamps=LEFT_ON, pressed=True, torque=-300)
    outs += d.step(F(0.1), state=S.preLaneChange, direction=D.left, lamps=LEFT_ON)
    assert set(outs) == {(True, False)}
  # a full second the other way does
  outs = d.step(F(AGAINST_TIME) + 1, state=S.preLaneChange, direction=D.left, lamps=LEFT_ON, pressed=True, torque=-300)
  assert outs[-3] == (True, False) and outs[-1] == (False, False)


def test_steering_against_during_the_change_does_not_end_it():
  d = Drive()
  d.step(1, lamps=RIGHT_ON)
  d.step(F(0.3), state=S.preLaneChange, direction=D.right, lamps=RIGHT_ON)
  outs = d.step(F(2.0), state=S.laneChangeStarting, direction=D.right, lamps=RIGHT_ON, pressed=True, torque=+250)
  assert set(outs) == {(False, True)}


def test_an_abandoned_lane_change_lets_go():
  d = Drive()
  d.step(1, lamps=LEFT_ON)
  d.step(F(0.3), state=S.preLaneChange, direction=D.left, lamps=LEFT_ON)
  d.step(F(1.0), state=S.laneChangeStarting, direction=D.left, lamps=LEFT_ON)
  assert d.step(1, state=S.off, lamps=LEFT_ON) == [(False, False)]


def test_the_other_direction_lets_go():
  d = Drive()
  d.step(1, lamps=LEFT_ON)
  d.step(F(0.3), state=S.preLaneChange, direction=D.left, lamps=LEFT_ON)
  assert d.step(1, state=S.preLaneChange, direction=D.right, lamps=LEFT_ON) == [(False, False)]


@pytest.mark.parametrize("lamps", ((False, True), (True, True)), ids=("other-side", "hazards"))
def test_other_side_or_hazards_end_it(lamps):
  d = Drive()
  d.step(1, lamps=LEFT_ON)
  d.step(F(0.3), state=S.preLaneChange, direction=D.left, lamps=LEFT_ON)
  assert d.step(1, state=S.preLaneChange, direction=D.left, lamps=lamps) == [(False, False)]
  # the driver's other-side signal stays the driver's own: it is not picked up as a new tap
  assert set(d.step(F(2.0), state=S.preLaneChange, direction=D.right, lamps=lamps)) == {(False, False)}


def test_hazards_coming_on_do_not_start_it():
  d = Drive()
  assert set(d.step(F(1.0), lamps=(True, True))) == {(False, False)}


@pytest.mark.parametrize("kw", (dict(lat=False), dict(v=LANE_CHANGE_SPEED - 0.5)), ids=("no-lateral", "slow"))
def test_does_not_start_without_lateral_or_below_lane_change_speed(kw):
  d = Drive()
  assert set(d.tap(**kw)) == {(False, False)}


def test_lateral_dropping_lets_go():
  d = Drive()
  d.step(1, lamps=LEFT_ON)
  d.step(F(0.3), state=S.preLaneChange, direction=D.left, lamps=LEFT_ON)
  assert d.step(1, state=S.preLaneChange, direction=D.left, lamps=LEFT_ON, lat=False) == [(False, False)]


def test_navigation_signals_are_left_to_navigation():
  d = Drive()
  # navigation asks: its lamps coming on are not the driver
  assert set(d.step(F(1.0), lamps=LEFT_ON, nav=(True, False))) == {(False, False)}
  d.step(F(1.0), nav=(False, False))
  # within NAV_QUIET of a navigation request, still not
  d2 = Drive()
  d2.step(F(0.5), nav=(True, False))
  assert d2.step(1, lamps=LEFT_ON)[0] == (False, False)
  # well after it, a tap is the driver's
  d3 = Drive()
  d3.step(F(0.5), nav=(True, False))
  d3.step(F(NAV_QUIET) + 1)
  assert d3.step(1, lamps=LEFT_ON) == [(True, False)]


def test_navigation_asking_for_the_other_side_lets_go():
  d = Drive()
  d.step(1, lamps=LEFT_ON)
  d.step(F(0.3), state=S.preLaneChange, direction=D.left, lamps=LEFT_ON)
  assert d.step(1, state=S.preLaneChange, direction=D.left, lamps=LEFT_ON, nav=(False, True)) == [(False, False)]


def test_never_longer_than_hold_max():
  d = Drive()
  d.step(1, lamps=LEFT_ON)
  outs = d.step(F(HOLD_MAX) + 5, state=S.laneChangeStarting, direction=D.left, lamps=LEFT_ON)
  assert outs[F(HOLD_MAX) - 5] == (True, False) and outs[-1] == (False, False)


def test_a_lamp_already_on_at_start_up_is_not_a_tap():
  lcs = LaneChangeSignal(True)
  assert lcs.update(S.off, D.none, True, False, SPEED, True, False, 0.0, False, False) == (False, False)


def test_a_new_tap_after_the_last_one_ended_is_held_again():
  d = Drive()
  d.step(1, lamps=LEFT_ON)
  lane_change(d)
  d.step(F(1.0))                                         # lamps out
  assert d.step(1, lamps=LEFT_ON) == [(True, False)]
