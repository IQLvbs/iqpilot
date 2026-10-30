# Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
import re
from pathlib import Path

import pytest

from iqpilot.common.realtime import DT_MDL
from iqpilot.selfdrive.controls.lib.accel_boost import (
  ACCEL_BOOST_DECAY_RATE, ACCEL_BOOST_MAX, ACCEL_BOOST_MIN_SPEED, ACCEL_BOOST_PER_OVERRIDE, ACCEL_BOOST_RATE, AccelBoost,
)

FAST = ACCEL_BOOST_MIN_SPEED + 5.0
SLOW = ACCEL_BOOST_MIN_SPEED - 1.0


def run(boost, seconds, engaged=True, v_ego=FAST, gas=True, model_limited=True):
  for _ in range(round(seconds / DT_MDL)):
    boost.update(engaged, v_ego, gas, model_limited)
  return boost.value


def eligible_boost():
  boost = AccelBoost(True, DT_MDL)
  boost.update(True, FAST, False, True)
  return boost


def test_param_is_off_by_default():
  keys = (Path(__file__).parents[3] / "common" / "params_keys.h").read_text()
  assert re.search(r'\{"IQGasOverrideBoost", \{PERSISTENT, BOOL, "0"\}\}', keys)


def test_disabled_never_boosts():
  boost = AccelBoost(False, DT_MDL)
  run(boost, DT_MDL, gas=False)
  assert run(boost, 30.0) == 0.0
  assert boost.apply(0.5) == 0.5


def test_gas_ramps_to_per_override_limit_and_holds():
  boost = eligible_boost()
  assert run(boost, 1.0) == pytest.approx(0.025, abs=1e-6)
  assert ACCEL_BOOST_RATE == 0.025
  assert ACCEL_BOOST_PER_OVERRIDE == 0.05
  assert run(boost, 15.0) == pytest.approx(0.05)
  assert run(boost, 5.0, gas=False) == pytest.approx(0.05)
  assert boost.override_boost == 0.0


def test_repeated_overrides_reach_total_limit():
  boost = eligible_boost()
  for _ in range(6):
    run(boost, 10.0)
    run(boost, DT_MDL, gas=False)
  assert ACCEL_BOOST_MAX == 0.2
  assert boost.value == pytest.approx(0.2)


def test_eligibility_is_latched_before_gas_override():
  boost = eligible_boost()
  assert run(boost, 1.0, model_limited=False) == pytest.approx(0.025)
  run(boost, DT_MDL, gas=False, model_limited=False)
  assert run(boost, 10.0, model_limited=True) == pytest.approx(0.025)
  run(boost, DT_MDL, gas=False, model_limited=True)
  assert run(boost, 1.0, model_limited=False) == pytest.approx(0.05)


def test_engaging_with_gas_pressed_does_not_latch_eligibility():
  boost = AccelBoost(True, DT_MDL)
  assert run(boost, 10.0) == 0.0


def test_bleeds_off_below_ten_mph_and_resets_on_disengage():
  boost = eligible_boost()
  run(boost, 5.0)
  assert ACCEL_BOOST_DECAY_RATE == 0.1
  assert run(boost, 0.2, v_ego=SLOW) == pytest.approx(0.03, abs=1e-6)
  assert run(boost, 5.0, v_ego=SLOW) == 0.0
  assert run(boost, 5.0) == 0.0
  run(boost, DT_MDL, gas=False)
  run(boost, 5.0)
  assert run(boost, DT_MDL, engaged=False) == 0.0
  assert boost.override_boost == 0.0
  assert boost.model_limited is False
  assert run(boost, 5.0) == 0.0


@pytest.mark.parametrize("accel,applied", [
  (-2.0, -2.0), (-1.0, -1.0), (-0.75, -0.725), (-0.5, -0.45),
  (0.0, 0.05), (5.0, 5.05), (5.01, 5.01),
])
def test_boost_fades_with_model_braking(accel, applied):
  boost = eligible_boost()
  run(boost, 5.0)
  assert boost.apply(accel) == pytest.approx(applied)


@pytest.mark.parametrize("a_model,a_ref,a_cruise,eligible", [
  (0.0, 0.5, 0.5, True),
  (0.0, 0.05, 0.5, False),
  (0.0, 0.5, 0.05, False),
  (0.0, 0.1, 0.5, False),
])
def test_planner_latches_model_limit_after_cruise_update(monkeypatch, a_model, a_ref, a_cruise, eligible):
  from types import SimpleNamespace
  import numpy as np

  from iqpilot.selfdrive.controls.lib import longitudinal_planner as lp
  from iqpilot.selfdrive.controls.lib.lead_assist.lead_assist import AssistOutput

  cruise_calls = []
  monkeypatch.setattr(lp, "get_cruise_accel", lambda *args: cruise_calls.append(args) or (a_cruise, False))
  planner = object.__new__(lp.LongitudinalPlanner)
  planner.CP = SimpleNamespace(openpilotLongitudinalControl=True, longitudinalActuatorDelay=0.1, steerRatio=15.0, wheelbase=2.7)
  planner.dt = DT_MDL
  planner.v_desired_filter = SimpleNamespace(x=FAST)
  planner.a_desired = 0.0
  planner.a_cruise = -1.0
  planner.allow_throttle = True
  planner.launch_armed = False
  planner.forcing_stop = False
  planner.accel_boost = AccelBoost(True, DT_MDL)
  planner.distance_control = SimpleNamespace(enabled=False, state=SimpleNamespace(active=False),
                                             update=lambda *args, **kwargs: kwargs["a_model"])
  planner.apply_e2e_stop_distance = lambda sm, v, a, stop: (a, stop)
  planner.assist = SimpleNamespace(
    lead_plan=None,
    update=lambda *args: AssistOutput(None, a_ref, False, False, False, False, lp.LongitudinalPlanSource.lead0))
  sm = {
    "carControl": SimpleNamespace(orientationNED=[], longActive=True),
    "carState": SimpleNamespace(vEgo=FAST, steeringAngleDeg=0.0, standstill=False, gasPressed=False),
    "selfdriveState": SimpleNamespace(enabled=True, personality=0),
    "vehicleParameters": SimpleNamespace(angleOffsetDeg=0.0),
    "modelV2": SimpleNamespace(action=SimpleNamespace(desiredAcceleration=a_model, shouldStop=False)),
    "radarState": SimpleNamespace(leadOne=SimpleNamespace(status=True), leadTwo=SimpleNamespace(status=False)),
  }
  model_v = np.full(len(lp.T_IDXS_PLAN), FAST)
  args = (sm, FAST, 100.0, lp.A_CRUISE_MIN, model_v, np.zeros(len(lp.T_IDXS_PLAN)), 0.15, False)
  planner.plan(*args)
  assert planner.accel_boost.model_limited is eligible
  sm["carState"].gasPressed = True
  output_a_target, _ = planner.plan(*args)
  assert planner.accel_boost.value == pytest.approx(ACCEL_BOOST_RATE * DT_MDL if eligible else 0.0)
  assert output_a_target == pytest.approx(min(a_cruise, planner.accel_boost.apply(a_model)))
  assert cruise_calls[-1][-1] == lp.A_CRUISE_MIN
  planner.plan(sm, FAST, 100.0, lp.A_CRUISE_MIN_NAV, model_v, np.zeros(len(lp.T_IDXS_PLAN)), 0.15, False)
  assert cruise_calls[-1][-1] == lp.A_CRUISE_MIN_NAV


def test_boost_bar_only_replaces_the_confidence_ball_with_the_param_on(monkeypatch):
  from types import SimpleNamespace

  from iqpilot.selfdrive.ui.mici.onroad import augmented_road_view
  view = SimpleNamespace(_boost_bar="bar", _confidence_ball="ball")
  for enabled, expected in ((False, "ball"), (True, "bar")):
    monkeypatch.setattr(augmented_road_view.ui_state, "gas_override_boost", enabled, raising=False)
    assert augmented_road_view.AugmentedRoadView._side_panel(view) == expected
