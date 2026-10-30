#!/usr/bin/env python3
import numpy as np

import iqpilot.cereal.messaging as messaging
from iqdbc.car.interfaces import ACCEL_MIN, ACCEL_MAX
from iqpilot.cereal import log
from iqpilot.common.constants import CV
from iqpilot.common.filter_simple import FirstOrderFilter
from iqpilot.common.params import Params, UnknownKeyName
from iqpilot.common.realtime import DT_MDL
from iqpilot.selfdrive.iqmodeld.config import ModelConstants
from iqpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from iqpilot.selfdrive.controls.lib.lead_assist.lead_plan import T_IDXS as T_IDXS_PLAN
from iqpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, DEFAULT_STOPPING_SPEED, get_accel_from_plan
from iqpilot.selfdrive.car.cruise import V_CRUISE_MAX, V_CRUISE_UNSET
from iqpilot.common.swaglog import cloudlog
from iqpilot.common.issue_debug import log_issue_limited

from iqpilot.selfdrive.controls.lib.speed_targets import SpeedTargets
from iqpilot.selfdrive.controls.lib.speed_targets import LongitudinalPlanSource as IQPlanSource
from iqpilot.selfdrive.controls.lib.accel_boost import AccelBoost
from iqpilot.selfdrive.controls.lib.cruise_accel import A_CRUISE_MIN, A_CRUISE_MIN_NAV, MIN_ALLOW_THROTTLE_SPEED
from iqpilot.selfdrive.controls.lib.cruise_accel import get_carcontrol_coast_accel, get_cruise_accel
from iqpilot.selfdrive.controls.lib.e2e_distance_controller import E2EDistanceController
from iqpilot.selfdrive.controls.lib.lead_assist.lead_assist import LeadAssist
from iqpilot.common.fastmath import clip as fast_clip, make_gradient

LongitudinalPlanSource = log.LongitudinalPlan.LongitudinalPlanSource

CONTROL_N_T_IDX = np.array(ModelConstants.T_IDXS[:CONTROL_N])
gradient_over_control_horizon = make_gradient(CONTROL_N_T_IDX)
ALLOW_THROTTLE_THRESHOLD = 0.4

LAUNCH_DISARM_SPEED = 2.0
LAUNCH_COMMIT_T = 3.5
LAUNCH_MOVING_SPEED = 1.2
LAUNCH_MAX_ACCEL = 1.5

E2E_CRUISE_CONVERGENCE_TAU = 15.0
E2E_CRUISE_ACCEL_MAX = 0.5
E2E_MODEL_SPEED_HORIZON = 5.0
E2E_ACCEL_INTENT_BP = [-0.05, 0.05]
E2E_MODEL_SPEED_INTENT_BP = [-0.5, 0.0]
E2E_TRAJECTORY_DECAY_TAU = 3.0
MODEL_LIMITED_MARGIN = 0.1


def get_lead_distance(radarState):
  if radarState.leadOne.status and (not radarState.leadTwo.status or radarState.leadOne.dRel < radarState.leadTwo.dRel):
    return radarState.leadOne.dRel
  if radarState.leadTwo.status:
    return radarState.leadTwo.dRel
  return 0


def get_e2e_accel(v_ego, v_cruise, model_v, a_target, should_stop):
  if should_stop or v_cruise <= v_ego or len(model_v) != len(T_IDXS_PLAN):
    return a_target

  accel = min((v_cruise - v_ego) / E2E_CRUISE_CONVERGENCE_TAU, E2E_CRUISE_ACCEL_MAX)
  if accel <= a_target:
    return a_target
  accel_intent = np.interp(a_target, E2E_ACCEL_INTENT_BP, [0.0, 1.0])
  model_speed = np.interp(E2E_MODEL_SPEED_HORIZON, T_IDXS_PLAN, model_v)
  speed_intent = np.interp(model_speed - v_ego, E2E_MODEL_SPEED_INTENT_BP, [0.0, 1.0])
  return float(np.interp(min(accel_intent, speed_intent), [0.0, 1.0], [a_target, accel]))


def rollout_trajectory(v_now, a_now, a_target):
  accels = a_target * np.exp(-CONTROL_N_T_IDX / E2E_TRAJECTORY_DECAY_TAU)
  accels[0] = a_now
  steps = np.diff(CONTROL_N_T_IDX) * (accels[1:] + accels[:-1]) / 2.0
  speeds = np.maximum(v_now + np.concatenate(([0.0], np.cumsum(steps))), 0.0)
  jerks = gradient_over_control_horizon(accels)
  return speeds, accels, jerks


class LongitudinalPlanner(SpeedTargets):
  def __init__(self, CP, CP_IQ, init_v=0.0, init_a=0.0, dt=DT_MDL):
    self.CP = CP
    self.stopping_speed = CP_IQ.longitudinalStoppingSpeedOverride or DEFAULT_STOPPING_SPEED
    SpeedTargets.__init__(self, self.CP, CP_IQ)
    self.assist = LeadAssist(dt, self.stopping_speed)
    self.fcw = False
    self.dt = dt
    self.allow_throttle = True

    self.a_desired = init_a
    self.v_desired_filter = FirstOrderFilter(init_v, 2.0, self.dt)
    self.a_cruise = init_a
    self.output_a_target = 0.0
    self.output_should_stop = False
    self.plan_source = LongitudinalPlanSource.cruise
    self.launch_armed = False
    try:
      distance_control_enabled = Params().get_bool("IQE2EDistanceControl")
    except UnknownKeyName:
      distance_control_enabled = False
    self.distance_control = E2EDistanceController(distance_control_enabled, dt)
    try:
      accel_boost_enabled = Params().get_bool("IQGasOverrideBoost")
    except UnknownKeyName:
      accel_boost_enabled = False
    self.accel_boost = AccelBoost(accel_boost_enabled, dt)

    self.active_lead_plan = self.assist.lead_plan
    self.v_desired_trajectory = np.zeros(CONTROL_N)
    self.a_desired_trajectory = np.zeros(CONTROL_N)
    self.j_desired_trajectory = np.zeros(CONTROL_N)

  @staticmethod
  def parse_model(model_msg):
    if (len(model_msg.position.x) == ModelConstants.IDX_N and
      len(model_msg.velocity.x) == ModelConstants.IDX_N and
      len(model_msg.acceleration.x) == ModelConstants.IDX_N):
      x = np.interp(T_IDXS_PLAN, ModelConstants.T_IDXS, model_msg.position.x)
      v = np.interp(T_IDXS_PLAN, ModelConstants.T_IDXS, model_msg.velocity.x)
      a = np.interp(T_IDXS_PLAN, ModelConstants.T_IDXS, model_msg.acceleration.x)
      j = np.zeros(len(T_IDXS_PLAN))
    else:
      x = np.zeros(len(T_IDXS_PLAN))
      v = np.zeros(len(T_IDXS_PLAN))
      a = np.zeros(len(T_IDXS_PLAN))
      j = np.zeros(len(T_IDXS_PLAN))
    if len(model_msg.meta.disengagePredictions.gasPressProbs) > 1:
      throttle_prob = model_msg.meta.disengagePredictions.gasPressProbs[1]
    else:
      throttle_prob = 1.0
    return x, v, a, j, throttle_prob

  def update(self, sm):
    SpeedTargets.update(self, sm)

    v_ego = sm['carState'].vEgo
    v_cruise_kph = min(sm['carState'].vCruise, V_CRUISE_MAX)
    v_cruise = v_cruise_kph * CV.KPH_TO_MS
    if sm['controlsState'].forceDecel:
      v_cruise = 0.0

    long_control_off = sm['controlsState'].longControlState == LongCtrlState.off

    reset_state = long_control_off if self.CP.openpilotLongitudinalControl else not sm['selfdriveState'].enabled
    v_cruise_initialized = sm['carState'].vCruise != V_CRUISE_UNSET
    reset_state = reset_state or not v_cruise_initialized

    if reset_state:
      self.v_desired_filter.x = v_ego
      self.a_desired = fast_clip(sm['carState'].aEgo, ACCEL_MIN, ACCEL_MAX)
      self.a_cruise = self.a_desired
      self.assist.reset()

    self.v_desired_filter.x = max(0.0, self.v_desired_filter.update(v_ego))
    _, model_v, model_a, _, throttle_prob = self.parse_model(sm['modelV2'])
    self.allow_throttle = throttle_prob > ALLOW_THROTTLE_THRESHOLD or v_ego <= MIN_ALLOW_THROTTLE_SPEED

    v_cruise = SpeedTargets.update_targets(self, sm, self.v_desired_filter.x, v_cruise)

    a_prev = self.a_desired
    min_accel = A_CRUISE_MIN_NAV if self.source == IQPlanSource.nav else A_CRUISE_MIN
    action_t = self.CP.longitudinalActuatorDelay + DT_MDL
    output_a_target, output_should_stop = self.plan(sm, v_ego, v_cruise, min_accel, model_v, model_a, action_t, reset_state)

    if self.fcw:
      cloudlog.info("FCW triggered")

    output_should_stop = output_should_stop or self.forcing_stop

    self.output_should_stop = bool(output_should_stop)
    self.output_a_target = fast_clip(output_a_target, ACCEL_MIN, ACCEL_MAX)

    self.a_desired = float(self.output_a_target)
    self.v_desired_filter.x = self.v_desired_filter.x + self.dt * (self.output_a_target + a_prev) / 2.0

  def plan(self, sm, v_ego, v_cruise, min_accel, model_v, model_a, action_t, reset_state):
    accel_coast = get_carcontrol_coast_accel(sm['carControl'])
    steer_angle_without_offset = sm['carState'].steeringAngleDeg - sm['vehicleParameters'].angleOffsetDeg
    personality = sm['selfdriveState'].personality
    radar_state = sm['radarState']
    has_lead = bool(radar_state.leadOne.status or radar_state.leadTwo.status)

    a_model = sm['modelV2'].action.desiredAcceleration
    stop_model = sm['modelV2'].action.shouldStop
    a_model, stop_model = self.apply_e2e_stop_distance(sm, v_ego, a_model, stop_model)
    if not has_lead:
      a_model = get_e2e_accel(v_ego, v_cruise, model_v, a_model, stop_model)

    if sm['carState'].standstill:
      self.launch_armed = True
    elif v_ego > LAUNCH_DISARM_SPEED:
      self.launch_armed = False
    if (self.launch_armed and not stop_model and
        np.interp(LAUNCH_COMMIT_T, T_IDXS_PLAN, model_v) > LAUNCH_DISARM_SPEED):
      t_cut = min(float(T_IDXS_PLAN[np.argmax(model_v > LAUNCH_MOVING_SPEED)]), LAUNCH_COMMIT_T)
      t_shifted = T_IDXS_PLAN + t_cut
      v_shifted = np.interp(t_shifted, T_IDXS_PLAN, model_v)
      a_shifted = np.interp(t_shifted, T_IDXS_PLAN, model_a)
      a_launch = get_accel_from_plan(v_shifted, a_shifted, T_IDXS_PLAN, action_t=action_t)[0]
      a_launch_max = np.interp(v_ego, [LAUNCH_MOVING_SPEED, LAUNCH_DISARM_SPEED], [LAUNCH_MAX_ACCEL, 0.])
      a_model = max(a_model, min(a_launch, a_launch_max))

    self.a_cruise, stop_cruise = get_cruise_accel(ACCEL_MAX, v_cruise, v_ego, self.a_cruise, self.dt, accel_coast,
                                                   self.allow_throttle, min_accel)

    engaged = bool(not reset_state and sm['selfdriveState'].enabled and sm['carControl'].longActive)
    assist = self.assist.update(sm, self.v_desired_filter.x, self.a_desired, a_model, personality, action_t, engaged)
    self.fcw = assist.fcw

    a_lead = assist.a_ref if assist.a_ref is not None else ACCEL_MAX
    model_limited = a_model < min(a_lead, self.a_cruise) - MODEL_LIMITED_MARGIN
    self.accel_boost.update(sm['selfdriveState'].enabled, v_ego, sm['carState'].gasPressed, model_limited)
    a_model = self.accel_boost.apply(a_model)

    if self.distance_control.enabled:
      lateral_accel = v_ego ** 2 * steer_angle_without_offset * CV.DEG_TO_RAD / (self.CP.steerRatio * self.CP.wheelbase)
    else:
      lateral_accel = 0.0
    a_model = self.distance_control.update(
      sm, self.assist.lead_plan, a_model=a_model, a_ref=a_lead, a_cruise=self.a_cruise,
      e2e=True, engaged=bool(self.CP.openpilotLongitudinalControl and engaged),
      should_stop=stop_model or assist.stop_ref or stop_cruise or self.forcing_stop,
      fcw=self.fcw, allow_throttle=self.allow_throttle, lateral_accel=lateral_accel,
    )

    candidates = [(self.a_cruise, LongitudinalPlanSource.cruise, stop_cruise), (a_model, LongitudinalPlanSource.e2e, stop_model)]
    if assist.active:
      candidates.insert(0, (assist.a_target, assist.source, assist.should_stop))
    elif self.distance_control.state.active and assist.a_ref is not None:
      candidates.insert(0, (assist.a_ref, assist.source, assist.stop_ref))
    output_a_target, self.plan_source, _ = min(candidates, key=lambda c: c[0])

    self.v_desired_trajectory, self.a_desired_trajectory, self.j_desired_trajectory = rollout_trajectory(
      self.v_desired_filter.x, self.a_desired, output_a_target)
    return output_a_target, any(should_stop for _, _, should_stop in candidates)

  def publish(self, sm, pm):
    plan_send = messaging.new_message('longitudinalPlan')

    gate_services = ['carState', 'controlsState', 'selfdriveState', 'radarState']
    plan_send.valid = sm.all_checks(service_list=gate_services)
    if not plan_send.valid:
      log_issue_limited(
        "longitudinal_plan_invalid",
        "planner",
        f"longitudinalPlan invalid alive={ {s: sm.alive[s] for s in gate_services} } "
        f"freq_ok={ {s: sm.freq_ok[s] for s in gate_services} } valid={ {s: sm.valid[s] for s in gate_services} } "
        f"subchecks=({sm.all_alive(gate_services)},{sm.all_freq_ok(gate_services)},{sm.all_valid(gate_services)}) "
        f"recheck={sm.all_checks(service_list=gate_services)}",
        interval_sec=5.0,
      )

    longitudinalPlan = plan_send.longitudinalPlan
    longitudinalPlan.modelMonoTime = sm.logMonoTime['modelV2']
    longitudinalPlan.processingDelay = (plan_send.logMonoTime / 1e9) - sm.logMonoTime['modelV2']
    longitudinalPlan.solverExecutionTime = self.active_lead_plan.solve_time

    longitudinalPlan.speeds = self.v_desired_trajectory.tolist()
    longitudinalPlan.accels = self.a_desired_trajectory.tolist()
    longitudinalPlan.jerks = self.j_desired_trajectory.tolist()

    longitudinalPlan.hasLead = sm['radarState'].leadOne.status
    longitudinalPlan.leadDistance = get_lead_distance(sm['radarState'])
    longitudinalPlan.longitudinalPlanSource = self.plan_source
    longitudinalPlan.fcw = self.fcw

    longitudinalPlan.leadTrajectoryX0 = self.active_lead_plan.lead_xv_0[:, 0].tolist()
    longitudinalPlan.leadTrajectoryV0 = self.active_lead_plan.lead_xv_0[:, 1].tolist()
    longitudinalPlan.leadTrajectoryX1 = self.active_lead_plan.lead_xv_1[:, 0].tolist()
    longitudinalPlan.leadTrajectoryV1 = self.active_lead_plan.lead_xv_1[:, 1].tolist()

    longitudinalPlan.aTarget = float(self.output_a_target)
    longitudinalPlan.shouldStop = bool(self.output_should_stop)
    longitudinalPlan.allowBrake = True
    longitudinalPlan.allowThrottle = bool(self.allow_throttle)

    pm.send('longitudinalPlan', plan_send)

    self.publish_iq_plan(sm, pm)
