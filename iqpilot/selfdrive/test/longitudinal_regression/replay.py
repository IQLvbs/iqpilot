"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from iqpilot.cereal import custom
from iqpilot.common.params import Params
from iqpilot.common.prefix import OpenpilotPrefix
from iqpilot.selfdrive.test.longitudinal_regression.frames import Frame
from iqpilot.selfdrive.test.longitudinal_regression.replay_state import ReplayState

PARAM_KEYS = (
  'LeadModelTrajectory', 'IQE2EDistanceControl', 'IQGasOverrideBoost', 'IQCustomStopDistance',
  'ExperimentalMode', 'LongitudinalPersonality', 'IQLeadApproachGuard',
)


LEGACY_PARAM_KEYS = {'newLeadMpc': 'LeadModelTrajectory'}


def _recorded_params(init_event):
  return {LEGACY_PARAM_KEYS.get(entry.key, entry.key): bytes(entry.value).decode()
          for entry in init_event.initData.params.entries if LEGACY_PARAM_KEYS.get(entry.key, entry.key) in PARAM_KEYS}


def _apply_params(recorded, overrides):
  params = Params()
  for key, value in {**recorded, **overrides}.items():
    try:
      params.put(key, value)
    except Exception:
      continue


def replay_events(events, make_planner, param_overrides=None, max_frames=None):
  events = sorted(events, key=lambda e: e.logMonoTime)
  frames = []
  with OpenpilotPrefix():
    recorded = {}
    cp = cp_iq = None
    for event in events:
      kind = event.which()
      if kind == 'initData' and not recorded:
        recorded = _recorded_params(event)
      elif kind == 'carParams' and cp is None:
        cp = event.carParams
      elif kind == 'iqCarParams' and cp_iq is None:
        cp_iq = event.iqCarParams
      if cp is not None and cp_iq is not None and recorded:
        break
    if cp is None:
      raise ValueError('log has no carParams')
    if cp_iq is None:
      cp_iq = custom.IQCarParams.new_message()
    _apply_params(recorded, param_overrides or {})

    planner = make_planner(cp, cp_iq)
    sm = ReplayState()
    last_plan = None
    t0 = None
    for event in events:
      kind = event.which()
      if kind == 'longitudinalPlan':
        last_plan = event.longitudinalPlan
        continue
      sm.feed(event)
      if kind != 'modelV2':
        continue
      required = {'carState', 'controlsState', 'selfdriveState', 'radarState'}
      if not required.issubset(sm.seen):
        continue
      if t0 is None:
        t0 = event.logMonoTime
      sm.frame += 1
      planner.update(sm)
      frames.append(_frame(sm, planner, (event.logMonoTime - t0) * 1e-9, last_plan))
      if max_frames and len(frames) >= max_frames:
        break
  return frames


def _source(planner):
  source = getattr(planner, 'plan_source', -1)
  return int(getattr(source, 'raw', source))


def _frame(sm, planner, t, plan):
  cs, rs, md, ss = sm['carState'], sm['radarState'], sm['modelV2'], sm['selfdriveState']
  lead = rs.leadOne
  return Frame(
    t=t, v_ego=float(cs.vEgo), a_ego=float(cs.aEgo), v_cruise=float(cs.vCruise),
    enabled=bool(ss.enabled), long_active=bool(sm['carControl'].longActive),
    personality=int(getattr(ss.personality, 'raw', ss.personality)),
    gas_pressed=bool(cs.gasPressed), brake_pressed=bool(cs.brakePressed), standstill=bool(cs.standstill),
    lead_status=bool(lead.status), lead_d=float(lead.dRel), lead_v=float(lead.vLead), lead_a=float(lead.aLeadK),
    lead_prob=float(lead.modelProb),
    model_a=float(md.action.desiredAcceleration), model_stop=bool(md.action.shouldStop),
    recorded_a=float(plan.aTarget) if plan is not None else float('nan'),
    recorded_stop=bool(plan.shouldStop) if plan is not None else False,
    recorded_source=int(plan.longitudinalPlanSource.raw) if plan is not None else -1,
    recorded_fcw=bool(plan.fcw) if plan is not None else False,
    a_target=float(planner.output_a_target), should_stop=bool(planner.output_should_stop),
    fcw=bool(getattr(planner, 'fcw', False)), source=_source(planner),
  )
