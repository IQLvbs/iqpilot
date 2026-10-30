#!/usr/bin/env python3
import time
import numpy as np
from iqpilot.cereal import log
from iqdbc.car.interfaces import ACCEL_MIN, ACCEL_MAX
from iqpilot.common.realtime import DT_MDL
from iqpilot.common.swaglog import cloudlog
from iqpilot.selfdrive.iqmodeld.config import index_function, ModelConstants
from iqpilot.selfdrive.controls.radard import _LEAD_ACCEL_TAU
from iqpilot.common.params import Params, UnknownKeyName
from iqpilot.selfdrive.controls.lib.lead_assist.lead_solver import COMFORT_BRAKE, STOP_DISTANCE, LeadTrajectorySolver
from iqpilot.common.fastmath import clip as fast_clip

try:
  from numpy._core.umath import clip as _clip
except ImportError:
  _clip = np.clip

LEAD_T_IDXS_MODEL = np.array(ModelConstants.LEAD_T_IDXS)

LongitudinalPlanSource = log.LongitudinalPlan.LongitudinalPlanSource
LEAD_SOURCES = (LongitudinalPlanSource.lead0, LongitudinalPlanSource.lead1)

X_DIM = 3
CRASH_DISTANCE = .25
USE_MODEL_LEAD_REFRESH_S = 0.2

N = 12
MAX_T = 10.0
T_IDXS_LST = [index_function(idx, max_val=MAX_T, max_idx=N) for idx in range(N+1)]

T_IDXS = np.array(T_IDXS_LST)
FCW_IDXS = T_IDXS < 5.0
FCW_COUNT = int(FCW_IDXS.sum())
T_DIFFS = np.diff(T_IDXS, prepend=[0.])
HALF_T_SQUARED = (T_IDXS ** 2) / 2.
MIN_X_LEAD_FACTOR = 0.5
LEAD_PULLAWAY_VREL = 0.5
LEAD_PULLAWAY_ABRAKE = -0.5

def get_jerk_factor(personality=log.LongitudinalPersonality.standard):
  if personality==log.LongitudinalPersonality.relaxed:
    return 1.0
  elif personality==log.LongitudinalPersonality.standard:
    return 1.0
  elif personality==log.LongitudinalPersonality.aggressive:
    return 0.5
  else:
    raise NotImplementedError("Longitudinal personality not supported")


def get_T_FOLLOW(personality=log.LongitudinalPersonality.standard):
  if personality==log.LongitudinalPersonality.relaxed:
    return 1.75
  elif personality==log.LongitudinalPersonality.standard:
    return 1.45
  elif personality==log.LongitudinalPersonality.aggressive:
    return 1.25
  else:
    raise NotImplementedError("Longitudinal personality not supported")

def get_stopped_equivalence_factor(v_lead):
  return (v_lead**2) / (2 * COMFORT_BRAKE)

def get_safe_obstacle_distance(v_ego, t_follow):
  return (v_ego**2) / (2 * COMFORT_BRAKE) + t_follow * v_ego + STOP_DISTANCE

class LeadPlan:
  def __init__(self, dt=DT_MDL):
    self.dt = dt
    self._params = Params()
    self.use_model_lead = self._read_use_model_lead()
    self._use_model_lead_read_t = -1e9
    self.solver = LeadTrajectorySolver(T_IDXS)
    self.reset()
    self.source = LongitudinalPlanSource.cruise

  def _read_use_model_lead(self) -> bool:
    try:
      return self._params.get_bool("LeadModelTrajectory")
    except UnknownKeyName:
      return False

  def reset(self):
    self.solver.reset()
    self.x_sol = np.zeros((N+1, X_DIM))
    self.v_solution = np.zeros(N+1)
    self.a_solution = np.zeros(N+1)
    self.j_solution = np.zeros(N)
    self.x_obstacle = np.full(N+1, 1e8)
    self.t_follow = get_T_FOLLOW()
    self.jerk_factor = get_jerk_factor()
    self.last_cloudlog_t = 0
    self.crash_cnt = 0.0
    self.solution_status = 0
    self.solve_time = 0.0
    self.x0 = np.zeros(X_DIM)
    self.lead_xv_0 = np.zeros((N+1, 2))
    self.lead_xv_1 = np.zeros((N+1, 2))

  def set_weights(self, personality=log.LongitudinalPersonality.standard):
    self.jerk_factor = get_jerk_factor(personality)

  def set_cur_state(self, v, a):
    self.x0[1] = v
    self.x0[2] = a

  @staticmethod
  def extrapolate_lead(x_lead, v_lead, a_lead, a_lead_tau):
    a_lead_traj = a_lead * np.exp((-a_lead_tau) * HALF_T_SQUARED)
    v_lead_traj = _clip(v_lead + (T_DIFFS * a_lead_traj).cumsum(), 0.0, 1e8)
    lead_xv = np.empty((len(T_IDXS), 2))
    lead_xv[:, 0] = x_lead + (T_DIFFS * v_lead_traj).cumsum()
    lead_xv[:, 1] = v_lead_traj
    return lead_xv

  def process_lead_legacy(self, lead):
    v_ego = self.x0[1]
    if lead is not None and lead.status:
      x_lead = lead.dRel
      v_lead = lead.vLead
      a_lead = lead.aLeadK
      a_lead_tau = lead.aLeadTau
    else:
      x_lead = 50.0
      v_lead = v_ego + 10.0
      a_lead = 0.0
      a_lead_tau = _LEAD_ACCEL_TAU

    min_x_lead = MIN_X_LEAD_FACTOR * (v_ego + v_lead) * (v_ego - v_lead) / (-ACCEL_MIN * 2)
    x_lead = fast_clip(x_lead, min_x_lead, 1e8)
    v_lead = fast_clip(v_lead, 0.0, 1e8)
    a_lead = fast_clip(a_lead, -10., 5.)
    lead_xv = self.extrapolate_lead(x_lead, v_lead, a_lead, a_lead_tau)
    return lead_xv

  def process_lead(self, model_lead, radar_lead):
    v_ego = self.x0[1]
    try:
      x_model = np.asarray(model_lead.x, dtype=np.float64)
      v_model = np.asarray(model_lead.v, dtype=np.float64)
      valid_model_lead = (float(model_lead.prob) > 0.5 and radar_lead.status and float(radar_lead.modelProb) > 0.5 and
                          x_model.shape == LEAD_T_IDXS_MODEL.shape and v_model.shape == LEAD_T_IDXS_MODEL.shape and
                          np.all(np.isfinite(x_model)) and np.all(np.isfinite(v_model)))
    except (AttributeError, TypeError, ValueError):
      valid_model_lead = False

    if not valid_model_lead:
      return self.process_lead_legacy(radar_lead)

    pulling_away = radar_lead.vRel > LEAD_PULLAWAY_VREL and radar_lead.aLeadK > LEAD_PULLAWAY_ABRAKE
    displacement = x_model - x_model[0]
    v_delta = v_model - v_model[0]
    if not pulling_away:
      displacement = np.minimum(displacement, max(float(radar_lead.vLead), 0.0) * LEAD_T_IDXS_MODEL)
      v_delta = np.minimum(v_delta, 0.0)

    x_lead_traj = float(radar_lead.dRel) + displacement
    v_lead_traj = float(radar_lead.vLead) + v_delta

    v_lead_0 = v_lead_traj[0]
    min_x_lead = MIN_X_LEAD_FACTOR * (v_ego + v_lead_0) * (v_ego - v_lead_0) / (-ACCEL_MIN * 2)
    x_lead_traj[0] = max(x_lead_traj[0], min_x_lead)
    v_lead_traj = np.clip(v_lead_traj, 0.0, 1e8)

    x_lead_plan = np.maximum.accumulate(np.interp(T_IDXS, LEAD_T_IDXS_MODEL, x_lead_traj))
    v_lead_plan = np.interp(T_IDXS, LEAD_T_IDXS_MODEL, v_lead_traj)
    if pulling_away:
      radar_velocity_floor = np.full_like(T_IDXS, float(radar_lead.vLead))
      radar_distance_floor = float(radar_lead.dRel) + float(radar_lead.vLead) * T_IDXS
      v_lead_plan = np.maximum(v_lead_plan, radar_velocity_floor)
      x_lead_plan = np.maximum(x_lead_plan, radar_distance_floor)
    return np.column_stack((x_lead_plan, v_lead_plan))

  def update(self, modelV2, radarstate, personality=log.LongitudinalPersonality.standard):
    now = time.monotonic()
    if now - self._use_model_lead_read_t >= USE_MODEL_LEAD_REFRESH_S:
      self.use_model_lead = self._read_use_model_lead()
      self._use_model_lead_read_t = now
    t_follow = get_T_FOLLOW(personality)
    model_leads = modelV2.leadsV3

    if self.use_model_lead:
      model_lead_0 = model_leads[0] if len(model_leads) > 0 else None
      model_lead_1 = model_leads[1] if len(model_leads) > 1 else None
      lead_xv_0 = self.process_lead(model_lead_0, radarstate.leadOne)
      lead_xv_1 = self.process_lead(model_lead_1, radarstate.leadTwo)
    else:
      lead_xv_0 = self.process_lead_legacy(radarstate.leadOne)
      lead_xv_1 = self.process_lead_legacy(radarstate.leadTwo)
    self.lead_xv_0 = lead_xv_0
    self.lead_xv_1 = lead_xv_1

    lead_0_obstacle = lead_xv_0[:,0] + get_stopped_equivalence_factor(lead_xv_0[:,1])
    lead_1_obstacle = lead_xv_1[:,0] + get_stopped_equivalence_factor(lead_xv_1[:,1])

    x_obstacles = np.column_stack([lead_0_obstacle, lead_1_obstacle])
    self.source = LEAD_SOURCES[np.argmin(x_obstacles[0])]

    self.x_obstacle = np.min(x_obstacles, axis=1)
    self.t_follow = t_follow

    self.run()
    lead_crash_prob = radarstate.leadOne.modelProb
    if (np.any(lead_xv_0[:FCW_COUNT, 0] - self.x_sol[:FCW_COUNT, 0] < CRASH_DISTANCE) and
            lead_crash_prob > 0.9):
      self.crash_cnt += 1
    else:
      self.crash_cnt = 0

  def run(self):
    started = time.perf_counter()
    states, _, cost = self.solver.solve(self.x0, self.x_obstacle, self.t_follow, self.jerk_factor, ACCEL_MIN, ACCEL_MAX)
    self.solve_time = time.perf_counter() - started
    if states is None or not np.all(np.isfinite(states)) or not np.isfinite(cost):
      t = time.monotonic()
      if t > self.last_cloudlog_t + 5.0:
        self.last_cloudlog_t = t
        cloudlog.warning(f"Lead trajectory solve failed, cost: {cost}")
      self.reset()
      self.solution_status = 1
      return

    self.x_sol = states
    self.v_solution = states[:, 1]
    self.a_solution = states[:, 2]
    self.j_solution = self.solver.u.copy()
    self.solution_status = 0
