"""Speed comfort inside the real planner: gentle where nothing is at stake, untouched everywhere else."""
import math

import numpy as np
import pytest

from iqdbc.car.honda.interface import CarInterface as HondaInterface
from iqdbc.car.honda.values import CAR as HONDA
from iqdbc.car.hyundai.interface import CarInterface as HyundaiInterface
from iqdbc.car.hyundai.values import CAR as HYUNDAI
from iqpilot.cereal import car, log
import iqpilot.cereal.messaging as messaging
from iqpilot.common.constants import CV
from iqpilot.common.params import Params
from iqpilot.selfdrive.controls.lib import longitudinal_planner
from iqpilot.selfdrive.controls.lib.longitudinal_planner import (A_CRUISE_MIN, A_CRUISE_MIN_NAV, J_CRUISE_BP, J_CRUISE_VALS, LongitudinalPlanner,
                                                                 get_cruise_accel)
from iqpilot.selfdrive.controls.lib.speed_comfort import (BEND_SHAPE, PICKUP_JERK, PICKUP_MARGIN, PICKUP_PATIENCE, RETURN_SHAPE, RUN_AHEAD_MARGIN,
                                                             TURN_ACCEL_V)
from iqpilot.selfdrive.iqmodeld.config import ModelConstants

DT = 0.05
LongState = car.CarControl.Actuators.LongControlState


@pytest.fixture(autouse=True)
def settings(monkeypatch, tmp_path):
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path / "params"))
  params = Params()
  params.put_bool("ExperimentalMode", True)
  params.put_bool("IQDynamicMode", False)
  params.put_bool("NavigationEnabled", True)
  params.put("IQSpeedAssistMode", 1)


def tucson(init_v=0.0):
  cp = HyundaiInterface.get_non_essential_params(HYUNDAI.HYUNDAI_TUCSON_4TH_GEN)
  return LongitudinalPlanner(cp, HyundaiInterface.get_non_essential_params_iq(cp, HYUNDAI.HYUNDAI_TUCSON_4TH_GEN), init_v=init_v)


def civic(init_v=0.0):
  cp = HondaInterface.get_non_essential_params(HONDA.HONDA_CIVIC)
  return LongitudinalPlanner(cp, HondaInterface.get_non_essential_params_iq(cp, HONDA.HONDA_CIVIC), init_v=init_v)


def scene(v_ego, a_ego=0.0, set_speed=40.0, model_accel=2.0, cruise_in_control=True, steer_deg=0.0, nav=None, force_decel=False, standstill=False):
  """One planner step's inputs with no car ahead. Speeds m/s, the set speed too; nav = (target m/s, provider) or None."""
  radar = messaging.new_message('radarState')
  control = messaging.new_message('controlsState')
  ss = messaging.new_message('selfdriveState')
  cs = messaging.new_message('carState')
  cc = messaging.new_message('carControl')
  model = messaging.new_message('modelV2')
  nav_state = messaging.new_message('iqNavState')

  times = np.array(ModelConstants.T_IDXS)
  position, velocity, acceleration = log.XYZTData.new_message(), log.XYZTData.new_message(), log.XYZTData.new_message()
  position.x = [float(v_ego * t) for t in times]
  velocity.x = [float(v_ego)] * len(times)
  acceleration.x = [0.0] * len(times)
  model.modelV2.position, model.modelV2.velocity, model.modelV2.acceleration = position, velocity, acceleration
  model.modelV2.action.desiredAcceleration = float(model_accel)
  model.modelV2.meta.disengagePredictions.gasPressProbs = [1.0] * 6

  control.controlsState.longControlState = LongState.pid if cruise_in_control else LongState.off
  control.controlsState.forceDecel = force_decel
  ss.selfdriveState.enabled = True
  ss.selfdriveState.experimentalMode = True
  cs.carState.vEgo = float(v_ego)
  cs.carState.aEgo = float(a_ego)
  cs.carState.vCruise = float(set_speed * CV.MS_TO_KPH)
  cs.carState.vCruiseCluster = float(set_speed * CV.MS_TO_KPH)
  cs.carState.steeringAngleDeg = float(steer_deg)
  cs.carState.standstill = standstill
  cc.carControl.longActive = cruise_in_control
  cc.carControl.orientationNED = [0.0, 0.0, 0.0]
  if nav is not None:
    nav_state.iqNavState.longitudinalEngaged = True
    nav_state.iqNavState.valid = True
    nav_state.iqNavState.speedTarget = float(nav[0])
    nav_state.iqNavState.longitudinalProvider = nav[1]
  return {'radarState': radar.radarState, 'controlsState': control.controlsState, 'selfdriveState': ss.selfdriveState, 'carState': cs.carState,
          'carControl': cc.carControl, 'vehicleParameters': messaging.new_message('vehicleParameters').vehicleParameters, 'modelV2': model.modelV2,
          'iqCarState': messaging.new_message('iqCarState').iqCarState, 'iqNavState': nav_state.iqNavState,
          'iqLiveData': messaging.new_message('iqLiveData').iqLiveData, 'iqLiveLocation': messaging.new_message('iqLiveLocation').iqLiveLocation,
          'iqConstructionZone': messaging.new_message('iqConstructionZone').iqConstructionZone,
          'gpsLocation': messaging.new_message('gpsLocation').gpsLocation, 'gpsLocationExternal': messaging.new_message('gpsLocation').gpsLocation}


def run(planner, seconds, **kwargs):
  out = []
  for _ in range(int(round(seconds / DT))):
    planner.update(scene(**kwargs))
    out.append(float(planner.output_a_target))
  return np.array(out)


def wheel_angle_for(planner, v_ego, lateral_accel):
  return math.degrees(lateral_accel * planner.CP.steerRatio * planner.CP.wheelbase / v_ego ** 2)


def test_only_the_tucson_has_the_layer():
  assert tucson().speed_comfort and tucson().pickup is not None
  assert not civic().speed_comfort and civic().pickup is None


def test_the_cruise_candidate_is_the_release_formula_when_no_shape_is_given():
  cp = tucson().CP
  rng = np.random.default_rng(7)
  for _ in range(3000):
    v_cruise, v_ego = float(rng.uniform(0.0, 40.0)), float(rng.uniform(0.0, 40.0))
    a_cruise_prev, a_target_prev = float(rng.uniform(-3.0, 2.0)), float(rng.uniform(-3.0, 2.0))
    for e2e, min_accel in ((True, A_CRUISE_MIN), (True, A_CRUISE_MIN_NAV), (False, A_CRUISE_MIN)):
      got, _ = get_cruise_accel(e2e, v_cruise, v_ego, a_cruise_prev, a_target_prev, 0.0, cp, DT, 0.0, True, min_accel)
      max_accel = longitudinal_planner.ACCEL_MAX if e2e else min(longitudinal_planner.get_max_accel(v_ego),
                                                                 np.interp(v_ego, longitudinal_planner._A_TOTAL_MAX_BP, longitudinal_planner._A_TOTAL_MAX_V))
      jerk = np.interp(v_ego, J_CRUISE_BP, J_CRUISE_VALS)
      want = float(np.clip(np.clip(v_cruise - v_ego, min_accel, max_accel), min(a_cruise_prev, a_target_prev) - jerk * DT, a_cruise_prev + jerk * DT))
      assert got == want


def test_above_the_set_speed_the_tucson_eases_down_and_another_car_brakes_as_before():
  gentle = run(tucson(init_v=20.0), 6.0, v_ego=20.0, set_speed=11.0)
  assert gentle.min() == pytest.approx(RETURN_SHAPE.min_accel)
  assert np.diff(gentle).min() >= -RETURN_SHAPE.jerk_brake * DT - 1e-9
  firm = run(civic(init_v=20.0), 6.0, v_ego=20.0, set_speed=11.0)
  assert firm.min() == pytest.approx(A_CRUISE_MIN)
  assert np.diff(firm).min() < -RETURN_SHAPE.jerk_brake * DT - 0.01


def test_a_small_overspeed_gets_a_small_request():
  out = run(tucson(init_v=16.0), 4.0, v_ego=16.0, set_speed=15.0)
  assert out[-1] == pytest.approx(-RETURN_SHAPE.gain_above * 1.0)
  assert run(civic(init_v=16.0), 4.0, v_ego=16.0, set_speed=15.0)[-1] == pytest.approx(-1.0)


def test_forced_deceleration_keeps_the_release_braking():
  out = run(tucson(init_v=20.0), 6.0, v_ego=20.0, set_speed=30.0, force_decel=True)
  assert out.min() == pytest.approx(A_CRUISE_MIN)


def test_the_driving_models_own_braking_is_not_softened():
  out = run(tucson(init_v=20.0), 3.0, v_ego=20.0, set_speed=11.0, model_accel=-2.5)
  assert out[-1] == pytest.approx(-2.5)
  assert out[0] == pytest.approx(-2.5)


def test_the_camera_bend_target_is_followed_gently_and_a_route_target_as_before():
  gentle = run(tucson(init_v=17.0), 6.0, v_ego=17.0, set_speed=30.0, nav=(11.5, "vision"))
  assert gentle.min() == pytest.approx(BEND_SHAPE.min_accel)
  assert np.diff(gentle).min() >= -BEND_SHAPE.jerk_brake * DT - 1e-9
  for provider in ("route", "mapbox"):
    firm = run(tucson(init_v=17.0), 6.0, v_ego=17.0, set_speed=30.0, nav=(11.5, provider))
    assert firm.min() == pytest.approx(A_CRUISE_MIN_NAV)


def test_reaching_the_set_speed_tapers_earlier():
  near = run(tucson(init_v=14.0), 3.0, v_ego=14.0, set_speed=15.0)
  assert near[-1] == pytest.approx(RETURN_SHAPE.gain_below * 1.0)
  assert run(civic(init_v=14.0), 3.0, v_ego=14.0, set_speed=15.0)[-1] == pytest.approx(1.0)
  far = run(tucson(init_v=5.0), 4.0, v_ego=5.0, a_ego=2.0, set_speed=15.0)
  assert far[-1] == pytest.approx(2.0)                                     # far below the set speed nothing changes


def test_taking_over_while_moving_waits_for_the_car():
  planner = tucson(init_v=5.0)
  run(planner, 0.5, v_ego=5.0, a_ego=0.0, cruise_in_control=False)        # the driver has lifted off
  held = run(planner, 0.6, v_ego=5.0, a_ego=0.0)                          # cruise takes over; the car has let go of the drive
  assert held.max() <= PICKUP_MARGIN + PICKUP_PATIENCE * 0.6 + 1e-6
  assert np.diff(held).max() <= PICKUP_JERK * DT + 1e-9
  answered = run(planner, 4.0, v_ego=5.0, a_ego=1.5)                      # the car answers
  assert np.diff(np.r_[held[-1], answered]).max() <= PICKUP_JERK * DT + 1e-9
  assert answered[-1] == pytest.approx(2.0)
  assert planner.pickup.window == 0.0

  other = civic(init_v=5.0)
  run(other, 0.5, v_ego=5.0, a_ego=0.0, cruise_in_control=False)
  assert run(other, 0.6, v_ego=5.0, a_ego=0.0).max() > 0.9                # the release runs ahead of the car


def test_taking_over_near_standstill_is_a_launch_and_is_left_alone():
  planner, other = tucson(), civic()
  for p in (planner, other):
    run(p, 0.5, v_ego=0.5, cruise_in_control=False)
  assert np.array_equal(run(planner, 2.0, v_ego=0.5), run(other, 2.0, v_ego=0.5))


def test_braking_right_after_a_take_over_is_immediate():
  planner = tucson(init_v=15.0)
  run(planner, 0.5, v_ego=15.0, cruise_in_control=False)
  assert run(planner, 0.2, v_ego=15.0, model_accel=-3.0)[0] == pytest.approx(-3.0)


def test_cornering_holds_acceleration_back_only_on_the_tucson():
  planner, other = tucson(init_v=5.0), civic(init_v=5.0)
  angle = wheel_angle_for(planner, 5.0, 2.2)
  out = run(planner, 4.0, v_ego=5.0, a_ego=2.0, set_speed=30.0, steer_deg=angle)
  assert out[-1] == pytest.approx(TURN_ACCEL_V[-1])
  assert run(planner, 0.5, v_ego=5.0, a_ego=2.0, set_speed=30.0, steer_deg=-angle)[-1] == pytest.approx(TURN_ACCEL_V[-1])
  assert run(other, 4.0, v_ego=5.0, a_ego=2.0, set_speed=30.0, steer_deg=wheel_angle_for(other, 5.0, 2.2))[-1] == pytest.approx(2.0)


def test_the_planned_speed_waits_for_the_car_after_a_take_over_only_on_the_tucson():
  planner, other = tucson(init_v=5.0), civic(init_v=5.0)
  for p in (planner, other):
    run(p, 0.5, v_ego=5.0, a_ego=0.0, cruise_in_control=False)
  gaps, gaps_other = [], []
  for _ in range(16):                                                    # 0.8 s: the car has let go of the drive
    planner.update(scene(v_ego=5.0, a_ego=0.0))
    other.update(scene(v_ego=5.0, a_ego=0.0))
    gaps.append(planner.v_desired_trajectory[0] - 5.0)
    gaps_other.append(other.v_desired_trajectory[0] - 5.0)
  assert max(gaps) <= RUN_AHEAD_MARGIN + 0.1
  assert max(gaps_other) > max(gaps)
