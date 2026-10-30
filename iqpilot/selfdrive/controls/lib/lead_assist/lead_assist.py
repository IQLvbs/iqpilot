"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from collections import deque
from dataclasses import dataclass

import numpy as np

from iqdbc.car.interfaces import ACCEL_MIN
from iqpilot.cereal import log
from iqpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, get_accel_from_plan
from iqpilot.selfdrive.controls.lib.lead_assist.lead_plan import LeadPlan, get_T_FOLLOW
from iqpilot.selfdrive.controls.lib.lead_assist.lead_plan import T_IDXS as T_IDXS_PLAN
from iqpilot.selfdrive.iqmodeld.config import ModelConstants
from iqpilot.common.fastmath import clip as fast_clip

LongitudinalPlanSource = log.LongitudinalPlan.LongitudinalPlanSource

CONTROL_N_T_IDX = np.array(ModelConstants.T_IDXS[:CONTROL_N])
ENGAGE_BRAKE = (-1.4, -1.3, -1.0)
RELEASE_BRAKE = (-0.9, -0.7, -0.5)
ENGAGE_MARGIN = 0.5
RELEASE_MARGIN = 0.2
ENGAGE_PERSIST_S = 0.1
RELEASE_HOLD_S = 0.5
LOW_SPEED = 4.0
LOW_SPEED_MARGIN = 0.2
LOW_SPEED_HOLD_GAP = 4.0
LOW_SPEED_HOLD_ACCEL = 0.3
SAFE_TIME_GAP_FRACTION = 0.65
SAFE_TIME_GAP_RELEASE_MARGIN = 0.3
TIGHT_GAP_MIN_SPEED = 3.0
TIGHT_GAP_MARGIN = 0.1
URGENT_NEED = (1.2, 1.2, 1.1)
URGENT_MARGIN = 0.6
URGENT_RELEASE_FRACTION = 0.7
MIN_STOP_GAP = 3.0
NEED_FLOOR = 0.8
ASSIST_JERK_LIMIT = 3.0
FLOOR_ANTICIPATION = 1.25
FLOOR_DEEP_FRACTION = 0.85
CLOSING_SPEED_MIN = 0.3
EMERGENCY_NEED = 2.5
NEED_GAIN = 1.0
SERIOUS_NEED = 1.5
SERIOUS_NEED_FULL = 3.0
SERIOUS_NEED_GAIN = 1.3
LEAD_BRAKING_MIN = 0.3
LEAD_BRAKING_MAX = 4.0
PLAN_HORIZON_S = 3.0
PLAN_MASK = CONTROL_N_T_IDX <= PLAN_HORIZON_S
MIN_LEAD_PROB = 0.5
GAP_RATE_WINDOW_S = 1.5
GAP_JUMP_RESET = 8.0


def required_decel(v_ego, lead_d, lead_v, lead_a):
  lead_v = np.maximum(lead_v, 0.0)
  room = np.maximum(lead_d - MIN_STOP_GAP, 0.5)
  closing = np.maximum(v_ego - lead_v, 0.0)
  lead_decel = fast_clip(-lead_a, 0.0, LEAD_BRAKING_MAX)
  relative = closing ** 2 / (2.0 * room) + lead_decel
  braking = lead_decel > LEAD_BRAKING_MIN
  lead_travel = np.where(braking, lead_v ** 2 / (2.0 * np.maximum(lead_decel, LEAD_BRAKING_MIN)), 0.0)
  until_stop = np.where(braking, v_ego ** 2 / (2.0 * (room + lead_travel)), 0.0)
  return np.where(v_ego >= lead_v, np.maximum(relative, until_stop), 0.0)


def _fmax(a, b):
  return a if (a >= b or a != a) else b


def _square(x):
  try:
    return x ** 2
  except OverflowError:
    return float(np.float64(x) ** 2)


def required_decel_scalar(v_ego, lead_d, lead_v, lead_a):
  lead_v = _fmax(lead_v, 0.0)
  room = _fmax(lead_d - MIN_STOP_GAP, 0.5)
  closing = _fmax(v_ego - lead_v, 0.0)
  lead_decel = float(fast_clip(-lead_a, 0.0, LEAD_BRAKING_MAX))
  relative = _square(closing) / (2.0 * room) + lead_decel
  if lead_decel > LEAD_BRAKING_MIN:
    lead_travel = _square(lead_v) / (2.0 * _fmax(lead_decel, LEAD_BRAKING_MIN))
    until_stop = _square(v_ego) / (2.0 * (room + lead_travel))
  else:
    until_stop = 0.0
  if v_ego >= lead_v:
    return _fmax(relative, until_stop)
  return 0.0


_POLYFIT_CACHE = {}


def _gap_slope(gaps, dt):
  key = (len(gaps), dt)
  cached = _POLYFIT_CACHE.get(key)
  if cached is None:
    x = np.arange(len(gaps)) * dt + 0.0
    lhs = np.vander(x, 2)
    scale = np.sqrt((lhs * lhs).sum(axis=0))
    lhs /= scale
    cached = _POLYFIT_CACHE[key] = (lhs, scale, len(x) * np.finfo(x.dtype).eps)
  lhs, scale, rcond = cached
  coefficients = np.linalg.lstsq(lhs, gaps + 0.0, rcond)[0]
  return (coefficients.T / scale).T[0]


@dataclass
class AssistOutput:
  a_target: float | None
  a_ref: float | None
  stop_ref: bool
  should_stop: bool
  fcw: bool
  active: bool
  source: int


class LeadAssist:
  def __init__(self, dt, stopping_speed):
    self.dt = dt
    self.stopping_speed = stopping_speed
    self.lead_plan = LeadPlan(dt=dt)
    self.active = False
    self.persist = 0.0
    self.release = 0.0
    self.reasons = (False, False, False, False)
    self.gap_history = deque(maxlen=int(GAP_RATE_WINDOW_S / dt) + 1)
    self.v_trajectory = np.zeros(CONTROL_N)
    self.a_trajectory = np.zeros(CONTROL_N)
    self.j_trajectory = np.zeros(CONTROL_N)

  def reset(self):
    self.active = False
    self.persist = 0.0
    self.release = 0.0

  @staticmethod
  def _required_decel(radar_state, v_ego, nearest_gap=None, nearest_speed=None):
    need = 0.0
    for lead in (radar_state.leadOne, radar_state.leadTwo):
      if lead.status and lead.modelProb >= MIN_LEAD_PROB:
        lead_v = nearest_speed if nearest_speed is not None and lead.dRel == nearest_gap else lead.vLead
        need = max(need, float(required_decel_scalar(v_ego, lead.dRel, lead_v, lead.aLeadK)))
    return need

  def _gap_rate_lead_speed(self, lead_gap, v_ego, reported_speed):
    if self.gap_history and abs(self.gap_history[-1][0] - lead_gap) > GAP_JUMP_RESET:
      self.gap_history.clear()
    self.gap_history.append((lead_gap, v_ego))
    if len(self.gap_history) < self.gap_history.maxlen or v_ego < LOW_SPEED:
      return reported_speed
    gaps = np.array([g for g, _ in self.gap_history])
    mean_ego = float(np.mean([v for _, v in self.gap_history]))
    slope = float(_gap_slope(gaps, self.dt))
    gap_speed = max(mean_ego + slope, 0.0)
    return min(reported_speed, gap_speed)

  def _has_lead(self, radar_state):
    return radar_state.leadOne.status or radar_state.leadTwo.status

  def update(self, sm, v_desired, a_desired, a_model, personality, action_t, engaged) -> AssistOutput:
    radar_state = sm['radarState']
    if not self._has_lead(radar_state):
      self.reset()
      self.gap_history.clear()
      self.lead_plan.crash_cnt = 0.0
      self.lead_plan.solve_time = 0.0
      self.lead_plan.solver.reset()
      self.lead_plan.lead_xv_0 = np.zeros_like(self.lead_plan.lead_xv_0)
      self.lead_plan.lead_xv_1 = np.zeros_like(self.lead_plan.lead_xv_1)
      return AssistOutput(None, None, False, False, False, False, self.lead_plan.source)

    self.lead_plan.set_weights(personality=personality)
    self.lead_plan.set_cur_state(v_desired, a_desired)
    self.lead_plan.update(sm['modelV2'], radar_state, personality=personality)
    self.v_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_PLAN, self.lead_plan.v_solution)
    self.a_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_PLAN, self.lead_plan.a_solution)
    self.j_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_PLAN[:-1], self.lead_plan.j_solution)

    fcw = bool(self.lead_plan.crash_cnt > 2 and not sm['carState'].standstill)
    a_ref, stop_ref = get_accel_from_plan(self.v_trajectory, self.a_trajectory, CONTROL_N_T_IDX,
                                          action_t=action_t, stopping_speed=self.stopping_speed)
    index = min(max(int(getattr(personality, 'raw', personality)), 0), len(ENGAGE_BRAKE) - 1)
    v_ego = float(sm['carState'].vEgo)

    nearest = min((lead for lead in (radar_state.leadOne, radar_state.leadTwo) if lead.status), key=lambda lead: lead.dRel)
    lead_gap = nearest.dRel
    lead_speed = self._gap_rate_lead_speed(lead_gap, v_ego, float(nearest.vLead))
    closing = v_ego - lead_speed > CLOSING_SPEED_MIN
    model_lagging = a_model > a_ref + ENGAGE_MARGIN
    hard_brake = float(np.min(self.a_trajectory[PLAN_MASK])) < ENGAGE_BRAKE[index] and model_lagging
    held_stop = (v_ego < LOW_SPEED and lead_gap < LOW_SPEED_HOLD_GAP and a_ref < LOW_SPEED_HOLD_ACCEL and
                 a_model > a_ref + LOW_SPEED_MARGIN)
    safe_time_gap = SAFE_TIME_GAP_FRACTION * get_T_FOLLOW(personality)
    time_gap = lead_gap / max(v_ego, 0.1)
    need = self._required_decel(radar_state, v_ego, lead_gap, lead_speed)
    urgent = need > URGENT_NEED[index] and a_model > -(need - URGENT_MARGIN)
    floor_trigger = safe_time_gap * (FLOOR_ANTICIPATION if closing else 1.0)
    tight = v_ego > TIGHT_GAP_MIN_SPEED and time_gap < floor_trigger and a_model > a_ref + TIGHT_GAP_MARGIN
    wants = engaged and (hard_brake or held_stop or tight or urgent)
    self.reasons = (hard_brake, held_stop, tight, urgent)

    if self.active:
      plan_eased = float(np.min(self.a_trajectory[PLAN_MASK])) > RELEASE_BRAKE[index] or a_model <= a_ref + RELEASE_MARGIN
      still_tight = (v_ego > TIGHT_GAP_MIN_SPEED and time_gap < floor_trigger + SAFE_TIME_GAP_RELEASE_MARGIN and
                     a_model > a_ref + TIGHT_GAP_MARGIN)
      still_urgent = need > URGENT_RELEASE_FRACTION * URGENT_NEED[index] and a_model > -(need - URGENT_MARGIN)
      settled = plan_eased and not (still_tight or held_stop or still_urgent)
      self.release = self.release + self.dt if settled else 0.0
      if self.release >= RELEASE_HOLD_S or not engaged:
        self.reset()
    else:
      self.persist = self.persist + self.dt if wants else 0.0
      if self.persist >= ENGAGE_PERSIST_S:
        self.active = True
        self.release = 0.0

    if not self.active:
      return AssistOutput(None, float(a_ref), bool(stop_ref), False, fcw, False, self.lead_plan.source)
    gain = NEED_GAIN + (SERIOUS_NEED_GAIN - NEED_GAIN) * float(fast_clip((need - SERIOUS_NEED) / (SERIOUS_NEED_FULL - SERIOUS_NEED), 0.0, 1.0))
    a_assist = min(a_ref, -gain * need) if need > NEED_FLOOR else a_ref
    inside_floor = v_ego > TIGHT_GAP_MIN_SPEED and time_gap < FLOOR_DEEP_FRACTION * safe_time_gap
    if need < EMERGENCY_NEED and not fcw and not inside_floor:
      a_assist = max(a_assist, a_desired - ASSIST_JERK_LIMIT * self.dt)
    return AssistOutput(float(max(a_assist, ACCEL_MIN)), float(a_ref), bool(stop_ref), bool(stop_ref), fcw, True, self.lead_plan.source)
