"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from types import SimpleNamespace

import pytest

from iqpilot.cereal import car
from iqpilot.selfdrive.controls.tests.lateral_control_scenarios import build_controls, load_controls_module, set_frame
from konn3kt_private.navd.known_turns import KNOWN_TURNS, KnownTurnAssist

TURN = KNOWN_TURNS[0]


@pytest.fixture
def controls_module(monkeypatch):
  return load_controls_module(monkeypatch)


def nav_message(distance):
  return SimpleNamespace(active=True, knownTurnId=TURN.turn_id, knownTurnStartDistance=TURN.start_distance,
                         knownTurnCurvature=TURN.signed_curvature, knownTurnHeading=TURN.heading_deg,
                         nextManeuverDistance=distance)


def drive_frame(controls, frame, distance, pressed=False):
  set_frame(controls, frame)
  controls.sm["carState"] = car.CarState.new_message(vEgo=6.5, steeringPressed=pressed)
  controls.sm["iqNavState"] = nav_message(distance)
  controls.sm.valid["iqNavState"] = True
  controls.sm.alive["iqNavState"] = True
  controls.sm.frame = frame
  controls.sm.recv_frame["iqNavState"] = frame
  controls.state_control()


def test_a_failed_model_is_lifted_to_the_catalogued_corner(controls_module):
  controls = build_controls(controls_module, "torque")
  controls.known_turn_assist = KnownTurnAssist()
  for frame in range(60, 70):
    drive_frame(controls, frame, distance=30.0)
  assert not controls.known_turn_assist.engaged
  assert controls.desired_curvature < 0.02
  for frame in range(70, 119):
    drive_frame(controls, frame, distance=1.0)
  assert controls.known_turn_assist.engaged
  assert controls.desired_curvature > 0.03


def test_a_driver_on_the_wheel_gets_the_model_alone(controls_module):
  controls = build_controls(controls_module, "torque")
  controls.known_turn_assist = KnownTurnAssist()
  for frame in range(60, 119):
    drive_frame(controls, frame, distance=1.0, pressed=True)
    assert controls.desired_curvature < 0.0215
  assert not controls.known_turn_assist.engaged
