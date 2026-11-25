# Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from iqpilot.cereal import custom, log
from iqpilot.common.constants import CV
from iqpilot.common.realtime import DT_MDL

SOURCE = Path(os.environ.get("IQ_PRIVATE_NAVD_DIR", Path(__file__).resolve().parents[5] / "konn3kt_private" / "navd")) / "action_engine.py"
TurnDirection = custom.IQTurnSignalDirection

pytestmark = pytest.mark.skipif(not SOURCE.exists(), reason="private navd source not present")


@pytest.fixture
def engine(monkeypatch):
  from iqpilot.selfdrive.controls.lib.helpers import lane_turn

  class FakeParams:
    def get(self, *_a, **_k):
      return None

    def get_bool(self, *_a, **_k):
      return True

    def get_int(self, *_a, **_k):
      return 0

  monkeypatch.setattr(lane_turn, "Params", FakeParams)
  spec = importlib.util.spec_from_file_location("navd_action_engine_under_test", SOURCE)
  module = importlib.util.module_from_spec(spec)
  monkeypatch.setattr("iqpilot.common.params.Params", FakeParams)
  spec.loader.exec_module(module)
  monkeypatch.setattr(module, "Params", FakeParams)
  return module.ActionEngine()


def carstate(left=False, right=False, v_mph=10.0):
  return SimpleNamespace(leftBlinker=left, rightBlinker=right, leftBlindspot=False, rightBlindspot=False,
                         vEgo=v_mph * CV.MPH_TO_MS, steeringPressed=False, steeringTorque=0.0, yawRate=0.0, brakePressed=False)


def step(engine, cs):
  engine.update(cs, True, 0.0)
  return engine.desire


def test_no_pulse_the_desire_stays_on_for_thirty_seconds_held(engine):
  frames = int(30.0 / DT_MDL)
  for _ in range(frames):
    assert step(engine, carstate(left=True)) == log.Desire.turnLeft


def test_desire_clears_the_frame_the_blinker_is_released(engine):
  for _ in range(40):
    step(engine, carstate(right=True))
  assert step(engine, carstate(right=True)) == log.Desire.turnRight
  assert step(engine, carstate()) == log.Desire.none


def test_desire_is_sent_from_standstill(engine):
  assert step(engine, carstate(left=True, v_mph=0.0)) == log.Desire.turnLeft


def test_lane_change_blinker_held_through_slowdown_gives_no_turn_desire(engine):
  step(engine, carstate(left=True, v_mph=40.0))
  for _ in range(100):
    assert step(engine, carstate(left=True, v_mph=8.0)) != log.Desire.turnLeft
  step(engine, carstate(v_mph=8.0))
  assert step(engine, carstate(left=True, v_mph=8.0)) == log.Desire.turnLeft
