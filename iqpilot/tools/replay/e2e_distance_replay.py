# Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

import argparse
from collections import Counter
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from iqpilot.common.realtime import DT_MDL
from iqpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, get_accel_from_plan
from iqpilot.selfdrive.controls.lib.e2e_distance_controller import E2EDistanceController
from iqpilot.selfdrive.controls.lib.lead_assist.lead_plan import LeadPlan
from iqdbc.car.interfaces import ACCEL_MAX
from iqpilot.selfdrive.controls.lib.cruise_accel import A_CRUISE_MIN, get_coast_accel, get_cruise_accel
from iqpilot.selfdrive.controls.lib.iq_chill.chill_planner import get_chill_max_accel
from iqpilot.selfdrive.iqmodeld.config import ModelConstants
from iqpilot.tools.lib.logreader import LogReader
from iqpilot.tools.lib.route import Route


class ReplayState(dict):
  def __init__(self):
    super().__init__()
    self.logMonoTime = {}
    self.valid = {}

  def all_checks(self, service_list):
    return all(self.valid.get(s, False) for s in service_list)

  def add(self, event):
    name = event.which()
    self[name] = getattr(event, name)
    self.logMonoTime[name] = event.logMonoTime
    self.valid[name] = bool(event.valid)


def replay(name):
  route = Route(name)
  controller = E2EDistanceController(True)
  solver = LeadPlan()
  sm = ReplayState()
  cp = None
  cruise_accel = 0.0
  segments = []
  commits = set()
  recorded_params = {}
  relevant = {'carParams', 'initData', 'carState', 'carControl', 'controlsState', 'selfdriveState',
              'modelV2', 'radarState', 'longitudinalPlan', 'iqPlan', 'iqCarState', 'vehicleParameters'}
  for segment, url in enumerate(route.log_paths()):
    if url is None:
      raise ValueError(f'Missing rlog segment {segment}')
    events = [event for event in LogReader(url) if event.which() in relevant]
    models = {event.logMonoTime: event for event in events if event.which() == 'modelV2'}
    counts = Counter()
    active_sources = Counter()
    corrections = []
    braking_corrections = []
    baseline_errors = []
    for event in sorted(events, key=lambda event: event.logMonoTime):
      kind = event.which()
      if kind == 'initData':
        commits.add(event.initData.gitCommit)
        keys = ['LeadModelTrajectory', 'expSpeedConv', 'IQCustomStopDistance', 'ExperimentalMode', 'LongitudinalPersonality']
        legacy_keys = {'newLeadMpc': 'LeadModelTrajectory'}
        recorded_params = {legacy_keys.get(entry.key, entry.key): bytes(entry.value).decode()
                           for entry in event.initData.params.entries if legacy_keys.get(entry.key, entry.key) in keys}
        continue
      if kind == 'carParams':
        cp = event.carParams
        continue
      sm.add(event)
      if kind != 'longitudinalPlan':
        continue
      plan = event.longitudinalPlan
      required = relevant - {'initData', 'carParams', 'longitudinalPlan'}
      if cp is None or not required.issubset(sm) or plan.modelMonoTime not in models:
        counts['unmatchedInputs'] += 1
        continue
      sm.add(models[plan.modelMonoTime])
      cs, md, ss = sm['carState'], sm['modelV2'], sm['selfdriveState']
      if len(plan.speeds) != CONTROL_N or len(plan.accels) != CONTROL_N:
        counts['invalidPlan'] += 1
        continue
      if recorded_params.get('IQCustomStopDistance') != '0':
        raise ValueError('Replay requires the recorded pure E2E mode and unmodified stop distance')
      solver._read_use_model_lead = lambda params=recorded_params: params.get('LeadModelTrajectory') == '1'
      solver.set_weights(ss.personality)
      solver.set_cur_state(plan.speeds[0], plan.accels[0])
      solver.update(md, sm['radarState'], ss.personality)
      a_ref, stop_ref = get_accel_from_plan(plan.speeds, plan.accels, ModelConstants.T_IDXS[:CONTROL_N],
                                          action_t=cp.longitudinalActuatorDelay + DT_MDL)
      e2e = bool(ss.experimentalMode)
      if str(sm['controlsState'].longControlState) == 'off':
        cruise_accel = cs.aEgo
      v_target = 0.0 if sm['controlsState'].forceDecel else sm['iqPlan'].vTarget
      pitch = sm['carControl'].orientationNED
      coast = get_coast_accel(pitch[1]) if len(pitch) == 3 else 2.0
      steer = cs.steeringAngleDeg - sm['vehicleParameters'].angleOffsetDeg
      max_accel = ACCEL_MAX if e2e else get_chill_max_accel(cs.vEgo, steer, cp)
      cruise_accel, stop_cruise = get_cruise_accel(max_accel, v_target, cs.vEgo, cruise_accel, DT_MDL, coast, plan.allowThrottle, A_CRUISE_MIN)
      lead_plan = SimpleNamespace(solution_status=solver.solution_status,
                            lead_xv_0=np.column_stack([plan.leadTrajectoryX0, plan.leadTrajectoryV0]),
                            lead_xv_1=np.column_stack([plan.leadTrajectoryX1, plan.leadTrajectoryV1]))
      a_model = md.action.desiredAcceleration
      kwargs = dict(a_model=a_model, a_ref=a_ref, a_cruise=cruise_accel, e2e=e2e,
                    engaged=bool(cp.openpilotLongitudinalControl and ss.enabled and sm['carControl'].longActive),
                    should_stop=bool(plan.shouldStop or stop_ref or stop_cruise), fcw=bool(plan.fcw),
                    allow_throttle=bool(plan.allowThrottle), lateral_accel=cs.vEgo ** 2 * steer * np.pi / 180 / (cp.steerRatio * cp.wheelbase))
      corrected = controller.update(sm, lead_plan, **kwargs)
      state = controller.state
      counts[state.inhibitionReason] += 1
      if state.active:
        active_sources[str(plan.longitudinalPlanSource)] += 1
        corrections.append(state.appliedCorrection)
        if a_model < 0:
          braking_corrections.append(state.appliedCorrection)
        assert corrected <= min(a_ref, cruise_accel) + 1e-9
        baseline_errors.append(abs(min(a_model, a_ref, cruise_accel) - plan.aTarget))
    result = {'segment': segment, 'counts': dict(counts), 'active_sources': dict(active_sources),
              'active_frames': len(corrections), 'mild_braking_frames': len(braking_corrections),
              'max_correction': max(corrections, default=0.0),
              'active_baseline_error_p99': float(np.percentile(baseline_errors, 99)) if baseline_errors else 0.0}
    segments.append(result)
    print(json.dumps({'route': name, **result}), flush=True)
  return {'route': name, 'commits': sorted(commits), 'recorded_params': recorded_params, 'segments': segments,
          'method': 'Frozen inputs: logged MPC trajectories, reconstructed cruise, fresh solver check. Not closed-loop validation.'}


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('routes', nargs='+')
  parser.add_argument('--output', type=Path, required=True)
  args = parser.parse_args()
  results = [replay(name) for name in args.routes]
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
  main()
