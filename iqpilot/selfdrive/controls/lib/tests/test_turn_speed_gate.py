# Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
import pytest

from iqpilot.cereal import custom
from iqpilot.common.constants import CV

TurnDirection = custom.IQTurnSignalDirection


def test_turn_speed_gate_is_fixed_at_twenty_mph_whatever_the_param_says(monkeypatch):
  from iqpilot.selfdrive.controls.lib.helpers import lane_turn

  class FakeParams:
    def get(self, *_a, **_k):
      return "30.0"

    def get_bool(self, *_a, **_k):
      return True

  monkeypatch.setattr(lane_turn, "Params", FakeParams)
  planner = lane_turn.TurnSignalPlanner(None)
  assert planner.speed_gate == pytest.approx(20.0 * CV.MPH_TO_MS)

  planner.sample(blink_l=True, speed_mps=19.0 * CV.MPH_TO_MS)
  assert planner.output() == TurnDirection.turnLeft

  planner.sample(blink_l=True, speed_mps=21.0 * CV.MPH_TO_MS)
  assert planner.output() == TurnDirection.none


def _planner(monkeypatch):
  from iqpilot.selfdrive.controls.lib.helpers import lane_turn

  class FakeParams:
    def get(self, *_a, **_k):
      return None

    def get_bool(self, *_a, **_k):
      return True

  monkeypatch.setattr(lane_turn, "Params", FakeParams)
  return lane_turn.TurnSignalPlanner(None)


FAST = 30.0 * CV.MPH_TO_MS
SLOW = 10.0 * CV.MPH_TO_MS


def test_blinker_held_from_highway_speed_through_a_slowdown_never_becomes_a_turn(monkeypatch):
  planner = _planner(monkeypatch)
  planner.sample(blink_l=True, speed_mps=FAST)
  assert planner.output() == TurnDirection.none
  for _ in range(300):
    planner.sample(blink_l=True, speed_mps=SLOW)
    assert planner.output() == TurnDirection.none


def test_fresh_blinker_below_the_gate_gives_a_turn_and_release_clears_it(monkeypatch):
  planner = _planner(monkeypatch)
  planner.sample(blink_r=True, speed_mps=SLOW)
  assert planner.output() == TurnDirection.turnRight
  planner.sample(blink_r=False, speed_mps=SLOW)
  assert planner.output() == TurnDirection.none


def test_released_lane_change_blinker_can_start_a_turn_on_the_next_activation(monkeypatch):
  planner = _planner(monkeypatch)
  planner.sample(blink_l=True, speed_mps=FAST)
  planner.sample(blink_l=False, speed_mps=SLOW)
  planner.sample(blink_l=True, speed_mps=SLOW)
  assert planner.output() == TurnDirection.turnLeft


def test_latch_is_per_side_and_a_side_switch_is_a_fresh_activation(monkeypatch):
  planner = _planner(monkeypatch)
  planner.sample(blink_l=True, speed_mps=FAST)
  planner.sample(blink_l=True, blink_r=False, speed_mps=SLOW)
  assert planner.output() == TurnDirection.none
  planner.sample(blink_l=False, blink_r=True, speed_mps=SLOW)
  assert planner.output() == TurnDirection.turnRight
  planner.sample(blink_l=True, blink_r=False, speed_mps=SLOW)
  assert planner.output() == TurnDirection.turnLeft


def test_turn_below_the_gate_persists_while_held_and_speeding_up_clears_it(monkeypatch):
  planner = _planner(monkeypatch)
  planner.sample(blink_l=True, speed_mps=SLOW)
  assert planner.output() == TurnDirection.turnLeft
  planner.sample(blink_l=True, speed_mps=FAST)
  assert planner.output() == TurnDirection.none


def test_turn_alerts_are_named_for_the_request():
  from iqpilot.selfdrive.selfdrived.iq_events import EVENTS_IQ
  from iqpilot.cereal import custom as c
  names = c.IQOnroadEvent.EventName
  assert EVENTS_IQ[names.modelTurnLeft][next(iter(EVENTS_IQ[names.modelTurnLeft]))].alert_text_1 == "Requesting Left Turn"
  assert EVENTS_IQ[names.modelTurnRight][next(iter(EVENTS_IQ[names.modelTurnRight]))].alert_text_1 == "Requesting Right Turn"


def _drive(planner, frames):
  return [(planner.sample(blink_l=l, blink_r=r, speed_mps=v * CV.MPH_TO_MS), planner.output())[1] for l, r, v in frames]


def test_hazards_after_a_lane_change_slowdown_request_no_turn(monkeypatch):
  planner = _planner(monkeypatch)
  frames = [(True, False, 35.0)] * 5 + [(True, False, 10.0)] * 5 + [(True, True, 10.0)] * 5 + [(True, False, 10.0)] * 5
  assert set(_drive(planner, frames)) == {TurnDirection.none}


def test_crossing_the_gate_mid_activation_latches_it_as_a_lane_change(monkeypatch):
  planner = _planner(monkeypatch)
  out = _drive(planner, [(True, False, 10.0)] * 3 + [(True, False, 20.0)] * 3 + [(True, False, 10.0)] * 5)
  assert out[:3] == [TurnDirection.turnLeft] * 3
  assert set(out[3:]) == {TurnDirection.none}


def test_hazards_from_standstill_request_no_turn_and_stay_non_turn_on_one_side(monkeypatch):
  planner = _planner(monkeypatch)
  out = _drive(planner, [(True, True, 0.0)] * 5 + [(False, True, 0.0)] * 5)
  assert set(out) == {TurnDirection.none}


def test_fresh_single_blinker_below_the_gate_after_hazards_gives_a_turn(monkeypatch):
  planner = _planner(monkeypatch)
  out = _drive(planner, [(True, True, 5.0)] * 3 + [(False, False, 5.0)] * 2 + [(False, True, 5.0)] * 3)
  assert out[:5] == [TurnDirection.none] * 5
  assert out[5:] == [TurnDirection.turnRight] * 3
