"""The Tucson's stop-point helper inside the real planner: the stop is finished where the driving model planned it."""
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
from iqpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
from iqpilot.selfdrive.controls.lib.smooth_stops import SMOOTH_STOP_MAX_SPEED
from iqpilot.selfdrive.controls.lib.stop_point import FREEZE_SPEED, StopPoint
from iqpilot.selfdrive.iqmodeld.config import ModelConstants

DT = 0.05
TIMES = np.array(ModelConstants.T_IDXS)
LongState = car.CarControl.Actuators.LongControlState


@pytest.fixture(autouse=True)
def settings(monkeypatch, tmp_path):
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path / "params"))
  params = Params()
  params.put_bool("ExperimentalMode", True)
  params.put_bool("IQDynamicMode", False)
  params.put("IQSpeedAssistMode", 1)


def tucson(init_v=0.0, stops_setting=True):
  cp = HyundaiInterface.get_non_essential_params(HYUNDAI.HYUNDAI_TUCSON_4TH_GEN)
  planner = LongitudinalPlanner(cp, HyundaiInterface.get_non_essential_params_iq(cp, HYUNDAI.HYUNDAI_TUCSON_4TH_GEN), init_v=init_v)
  # the stops setting (IQForceStops), as the planner reads it every frame
  planner.iq_dynamic._read_bool = lambda key, default: stops_setting if key == "IQForceStops" else default
  return planner


def civic(init_v=0.0):
  cp = HondaInterface.get_non_essential_params(HONDA.HONDA_CIVIC)
  return LongitudinalPlanner(cp, HondaInterface.get_non_essential_params_iq(cp, HONDA.HONDA_CIVIC), init_v=init_v)


def scene(v_ego, a_ego, room, model_accel, pilot=True, gas=False, lead=None, standstill=False, cruise_in_control=True):
  """One planner step on the way to a stop: the model's plan is a steady stop in `room` metres (None: it keeps its speed)."""
  radar = messaging.new_message('radarState')
  control = messaging.new_message('controlsState')
  ss = messaging.new_message('selfdriveState')
  cs = messaging.new_message('carState')
  cc = messaging.new_message('carControl')
  model = messaging.new_message('modelV2')

  if room is None:
    v_plan, x_plan = np.full(len(TIMES), float(v_ego)), v_ego * TIMES
  else:
    decel = v_ego ** 2 / (2.0 * max(room, 0.1))
    t_stop = v_ego / decel if decel > 0.0 else 0.0
    t = np.minimum(TIMES, t_stop)
    v_plan, x_plan = np.maximum(v_ego - decel * t, 0.0), v_ego * t - 0.5 * decel * t ** 2
  position, velocity, acceleration = log.XYZTData.new_message(), log.XYZTData.new_message(), log.XYZTData.new_message()
  position.x = [float(x) for x in x_plan]
  velocity.x = [float(v) for v in v_plan]
  acceleration.x = [0.0] * len(TIMES)
  model.modelV2.position, model.modelV2.velocity, model.modelV2.acceleration = position, velocity, acceleration
  model.modelV2.action.desiredAcceleration = float(model_accel)
  model.modelV2.meta.disengagePredictions.gasPressProbs = [1.0] * 6

  if lead is not None:
    radar.radarState.leadOne.status = True
    radar.radarState.leadOne.dRel = float(lead)
  control.controlsState.longControlState = LongState.pid if cruise_in_control else LongState.off
  ss.selfdriveState.enabled = True
  ss.selfdriveState.experimentalMode = pilot
  cs.carState.vEgo = float(v_ego)
  cs.carState.aEgo = float(a_ego)
  cs.carState.vCruise = float(20.0 * CV.MS_TO_KPH)
  cs.carState.vCruiseCluster = float(20.0 * CV.MS_TO_KPH)
  cs.carState.gasPressed = gas
  cs.carState.standstill = standstill
  cc.carControl.longActive = cruise_in_control
  cc.carControl.orientationNED = [0.0, 0.0, 0.0]
  return {'radarState': radar.radarState, 'controlsState': control.controlsState, 'selfdriveState': ss.selfdriveState, 'carState': cs.carState,
          'carControl': cc.carControl, 'vehicleParameters': messaging.new_message('vehicleParameters').vehicleParameters, 'modelV2': model.modelV2,
          'iqCarState': messaging.new_message('iqCarState').iqCarState, 'iqNavState': messaging.new_message('iqNavState').iqNavState,
          'iqLiveData': messaging.new_message('iqLiveData').iqLiveData, 'iqLiveLocation': messaging.new_message('iqLiveLocation').iqLiveLocation,
          'iqConstructionZone': messaging.new_message('iqConstructionZone').iqConstructionZone,
          'gpsLocation': messaging.new_message('gpsLocation').gpsLocation, 'gpsLocationExternal': messaging.new_message('gpsLocation').gpsLocation}


class Approach:
  """A car on the way to a line with the real planner in the loop. As in the logs, the model brakes steadily for the
  line; at a crawl its point drifts ahead of the car and the car rolls on at idle against a light brake."""
  def __init__(self, planner, v=12.0, line=60.0, **scene_kw):
    self.p, self.v, self.a, self.x, self.line, self.kw = planner, v, 0.0, 0.0, line, scene_kw
    self.hold = False
    self.rows = []

  def step(self, **kw):
    room = self.line - self.x
    slow = self.v < FREEZE_SPEED
    plan_room = max(room, 1.0) if slow else max(room, 0.5)
    a_model = -0.2 if slow else -min(self.v ** 2 / (2.0 * plan_room), 2.5)
    self.p.update(scene(self.v, self.a, plan_room, a_model, standstill=self.v < 0.02, **{**self.kw, **kw}))
    a, stop = float(self.p.output_a_target), bool(self.p.output_should_stop)
    self.rows.append((self.x - self.line, self.v, a, stop))
    if stop and self.v <= SMOOTH_STOP_MAX_SPEED:
      cmd = min(a, -(0.25 + 0.55 * min(self.v, 1.0)))                  # the speed controller's soft stop
    else:
      cmd = a + (0.6 if self.v < 1.0 else 0.0)                         # rolling on at idle
    self.a += (cmd - self.a) * DT / 0.2
    self.v = max(0.0, self.v + self.a * DT)
    self.hold = (self.hold or (stop and self.v < 0.05)) and a <= 0.3   # the speed controller's hold
    if self.hold:
      self.v = self.a = 0.0
    self.x += self.v * DT

  def drive(self, seconds, **kw):
    for _ in range(int(seconds / DT)):
      self.step(**kw)
    return self


def test_only_the_tucson_has_it():
  assert isinstance(tucson().stop_point, StopPoint)
  assert civic().stop_point is None


def test_the_tucson_stops_at_the_line_and_stays():
  run = Approach(tucson(12.0)).drive(40.0)
  assert run.v == 0.0
  assert abs(run.x - run.line) < 1.0
  rows = np.array(run.rows)
  rest = int(np.argmax(rows[:, 1] == 0.0))
  assert rows[rest:, 0].max() - rows[rest, 0] < 0.05                    # no rolling on after the stop


def test_without_it_the_same_approach_rolls_past_the_line():
  planner = tucson(12.0)
  planner.stop_point = None
  run = Approach(planner).drive(40.0)
  assert run.x - run.line > 1.5


def test_the_plan_is_identical_until_the_landing():
  with_it, without = tucson(12.0), tucson(12.0)
  without.stop_point = None
  run = Approach(with_it)
  while run.v > SMOOTH_STOP_MAX_SPEED + 0.1:
    room = run.line - run.x
    a_model = -min(run.v ** 2 / (2.0 * max(room, 0.5)), 2.5)
    without.update(scene(run.v, run.a, max(room, 0.5), a_model))
    run.step()
    assert float(with_it.output_a_target) == float(without.output_a_target)
    assert bool(with_it.output_should_stop) == bool(without.output_should_stop)
  assert with_it.stop_point.point is not None


def test_it_stays_out_when_not_in_pilot_mode():
  run = Approach(tucson(12.0), pilot=False).drive(12.0)
  assert run.p.stop_point.point is None and not run.p.stop_point.finishing


def test_it_stays_out_when_the_stops_setting_is_off():
  run = Approach(tucson(12.0, stops_setting=False)).drive(12.0)
  assert run.p.stop_point.point is None and not run.p.stop_point.finishing


def test_a_car_ahead_near_the_line_owns_the_stop():
  run = Approach(tucson(12.0)).drive(2.0)
  assert run.p.stop_point.point is not None
  run.step(lead=run.line - run.x + 2.0)
  assert run.p.stop_point.point is None


def test_the_accelerator_releases_it():
  run = Approach(tucson(12.0))
  for _ in range(400):
    if run.p.stop_point.finishing:
      break
    run.step()
  assert run.p.stop_point.finishing
  run.step(gas=True)
  assert run.p.stop_point.point is None and not run.p.stop_point.finishing
