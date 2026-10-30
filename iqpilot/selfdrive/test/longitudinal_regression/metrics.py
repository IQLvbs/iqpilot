"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import numpy as np

from iqpilot.common.realtime import DT_MDL
from iqpilot.selfdrive.controls.lib.lead_assist.lead_assist import required_decel as lead_required_decel

LEAD_SOURCES = (1, 2, 3)
HARD_BRAKE = -2.0
BRAKING_SHORTFALL_FLOOR = -1.0
NEED_FLOOR = 0.8
DEFICIT_MARGIN = 0.5


def _arr(frames, field, dtype=float):
  return np.array([getattr(f, field) for f in frames], dtype=dtype)


def _pct(values, q):
  return float(np.percentile(values, q)) if len(values) else 0.0


def engaged_mask(frames):
  return _arr(frames, 'long_active', bool) & _arr(frames, 'enabled', bool)


def jerk(a_target):
  return np.diff(a_target, prepend=a_target[:1]) / DT_MDL


def time_gap(frames):
  v = np.maximum(_arr(frames, 'v_ego'), 0.1)
  return np.where(_arr(frames, 'lead_status', bool), _arr(frames, 'lead_d') / v, np.inf)


def stop_events(frames):
  standstill = _arr(frames, 'standstill', bool)
  engaged = engaged_mask(frames)
  has_lead = _arr(frames, 'lead_status', bool)
  lead_d = _arr(frames, 'lead_d')
  starts = np.flatnonzero(standstill & ~np.concatenate(([False], standstill[:-1])) & engaged)
  return [{'t': float(frames[i].t), 'lead': bool(has_lead[i]), 'gap': float(lead_d[i]) if has_lead[i] else None} for i in starts]


def scorecard(frames):
  if not frames:
    return {'frames': 0}
  deficit = braking_deficit(frames, required_decel(frames))
  engaged = engaged_mask(frames)
  mask = engaged
  a = _arr(frames, 'a_target')
  rec = _arr(frames, 'recorded_a')
  model = _arr(frames, 'model_a')
  has_lead = _arr(frames, 'lead_status', bool)
  source = _arr(frames, 'recorded_source', int)
  v_ego = _arr(frames, 'v_ego')
  fidelity = np.abs(a - rec)[mask & ~np.isnan(rec)]
  lead_bound = mask & np.isin(source, LEAD_SOURCES)
  tg = time_gap(frames)
  following = mask & has_lead & (v_ego > 3.0)
  j = jerk(a)
  return {
    'frames': len(frames),
    'engaged_frames': int(mask.sum()),
    'engaged_seconds': float(mask.sum() * DT_MDL),
    'lead_frames': int((mask & has_lead).sum()),
    'recorded_lead_bound_frames': int(lead_bound.sum()),
    'replayed_lead_bound_frames': int((mask & np.isin(_arr(frames, 'source', int), LEAD_SOURCES)).sum()),
    'recorded_source_counts': {int(s): int(((source == s) & mask).sum()) for s in np.unique(source[mask])} if mask.any() else {},
    'fidelity_abs_err_p50': _pct(fidelity, 50),
    'fidelity_abs_err_p95': _pct(fidelity, 95),
    'fidelity_abs_err_max': float(fidelity.max()) if len(fidelity) else 0.0,
    'replay_vs_model_when_lead_bound_p50': _pct((a - model)[lead_bound], 50),
    'replay_vs_model_when_lead_bound_p5': _pct((a - model)[lead_bound], 5),
    'a_target_min': float(a[mask].min()) if mask.any() else 0.0,
    'a_target_p1': _pct(a[mask], 1),
    'a_target_p99': _pct(a[mask], 99),
    'jerk_p1': _pct(j[mask], 1),
    'jerk_p99': _pct(j[mask], 99),
    'hard_brake_frames': int((mask & (a < HARD_BRAKE)).sum()),
    'fcw_frames': int((_arr(frames, 'fcw', bool) & mask).sum()),
    'deficit_frames': int(((deficit > DEFICIT_MARGIN) & mask).sum()),
    'recorded_fcw_frames': int((_arr(frames, 'recorded_fcw', bool) & mask).sum()),
    'min_time_gap': float(tg[following].min()) if following.any() else None,
    'time_gap_p5': _pct(tg[following], 5) if following.any() else None,
    'time_gap_p50': _pct(tg[following], 50) if following.any() else None,
    'takeover_frames': int((_arr(frames, 'gas_pressed', bool) | _arr(frames, 'brake_pressed', bool))[mask].sum()),
    'stops': stop_events(frames),
  }


def required_decel(frames):
  need = lead_required_decel(_arr(frames, 'v_ego'), _arr(frames, 'lead_d'), _arr(frames, 'lead_v'), _arr(frames, 'lead_a'))
  return np.where(_arr(frames, 'lead_status', bool), need, 0.0)


def braking_deficit(frames, need):
  decel = np.maximum(-_arr(frames, 'a_target'), 0.0)
  return np.where(need > NEED_FLOOR, np.maximum(need - decel, 0.0), 0.0)


def compare(base_frames, cand_frames):
  n = min(len(base_frames), len(cand_frames))
  base, cand = base_frames[:n], cand_frames[:n]
  mask = engaged_mask(base)
  ab, ac = _arr(base, 'a_target'), _arr(cand, 'a_target')
  has_lead = _arr(base, 'lead_status', bool)
  delta = (ac - ab)[mask]
  shortfall = np.maximum(ac - ab, 0.0)
  braking = mask & (ab < BRAKING_SHORTFALL_FLOOR)
  stop_base, stop_cand = _arr(base, 'should_stop', bool), _arr(cand, 'should_stop', bool)
  lead_braking = braking & has_lead
  need = required_decel(base)
  deficit_base, deficit_cand = braking_deficit(base, need), braking_deficit(cand, need)
  needy = mask & (need > NEED_FLOOR)
  worst = np.argsort(-(deficit_cand - deficit_base) * mask)[:5]
  return {
    'frames': n,
    'engaged_frames': int(mask.sum()),
    'need_frames': int(needy.sum()),
    'deficit_base_frames': int(((deficit_base > DEFICIT_MARGIN) & mask).sum()),
    'deficit_cand_frames': int(((deficit_cand > DEFICIT_MARGIN) & mask).sum()),
    'deficit_base_max': float(deficit_base[mask].max()) if mask.any() else 0.0,
    'deficit_cand_max': float(deficit_cand[mask].max()) if mask.any() else 0.0,
    'worst_frames': [{'i': int(i), 't': float(base[i].t), 'v_ego': base[i].v_ego, 'lead_d': base[i].lead_d, 'lead_v': base[i].lead_v,
                      'need': float(need[i]), 'base_a': float(ab[i]), 'cand_a': float(ac[i]), 'model_a': base[i].model_a}
                     for i in worst if (deficit_cand - deficit_base)[i] > 0.0],
    'delta_p1': _pct(delta, 1), 'delta_p50': _pct(delta, 50), 'delta_p99': _pct(delta, 99),
    'delta_abs_max': float(np.abs(delta).max()) if len(delta) else 0.0,
    'braking_frames': int(braking.sum()),
    'braking_shortfall_p95': _pct(shortfall[braking], 95),
    'braking_shortfall_max': float(shortfall[braking].max()) if braking.any() else 0.0,
    'lead_braking_frames': int(lead_braking.sum()),
    'lead_braking_shortfall_p95': _pct(shortfall[lead_braking], 95),
    'lead_braking_shortfall_max': float(shortfall[lead_braking].max()) if lead_braking.any() else 0.0,
    'stop_disagree_frames': int((stop_base != stop_cand)[mask].sum()),
    'fcw_base_frames': int((_arr(base, 'fcw', bool) & mask).sum()),
    'fcw_cand_frames': int((_arr(cand, 'fcw', bool) & mask).sum()),
    'cand': scorecard(cand),
    'base': scorecard(base),
  }
