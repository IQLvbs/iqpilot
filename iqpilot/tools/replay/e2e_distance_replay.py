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
from iqpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import LongitudinalMpc
from iqpilot.selfdrive.controls.lib.longitudinal_planner import get_cruise_accel, get_coast_accel
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
  solver = LongitudinalMpc()
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
        keys = ['newLeadMpc', 'expSpeedConv', 'IQCustomStopDistance', 'ExperimentalMode', 'IQDynamicMode', 'LongitudinalPersonality']
        recorded_params = {entry.key: bytes(entry.value).decode() for entry in event.initData.params.entries if entry.key in keys}
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
      if recorded_params.get('IQCustomStopDistance') != '0' or recorded_params.get('IQDynamicMode') != '0':
        raise ValueError('Replay requires the recorded pure E2E mode and unmodified stop distance')
      solver._read_new_lead_mpc = lambda params=recorded_params: params.get('newLeadMpc') == '1'
      solver.set_weights(ss.personality)
      solver.set_cur_state(plan.speeds[0], plan.accels[0])
      solver.update(md, sm['radarState'], ss.personality)
      a_mpc, stop_mpc = get_accel_from_plan(plan.speeds, plan.accels, ModelConstants.T_IDXS[:CONTROL_N],
                                          action_t=cp.longitudinalActuatorDelay + DT_MDL)
      e2e = bool(ss.experimentalMode)
      if str(sm['controlsState'].longControlState) == 'off':
        cruise_accel = cs.aEgo
      v_target = 0.0 if sm['controlsState'].forceDecel else sm['iqPlan'].vTarget
      pitch = sm['carControl'].orientationNED
      coast = get_coast_accel(pitch[1]) if len(pitch) == 3 else 2.0
      steer = cs.steeringAngleDeg - sm['vehicleParameters'].angleOffsetDeg
      cruise_accel, stop_cruise = get_cruise_accel(e2e, v_target, cs.vEgo, cruise_accel, steer, cp, DT_MDL, coast, plan.allowThrottle)
      mpc = SimpleNamespace(solution_status=solver.solution_status,
                            lead_xv_0=np.column_stack([plan.leadTrajectoryX0, plan.leadTrajectoryV0]),
                            lead_xv_1=np.column_stack([plan.leadTrajectoryX1, plan.leadTrajectoryV1]))
      a_model = md.action.desiredAcceleration
      kwargs = dict(a_model=a_model, a_mpc=a_mpc, a_cruise=cruise_accel, e2e=e2e,
                    engaged=bool(cp.openpilotLongitudinalControl and ss.enabled and sm['carControl'].longActive),
                    should_stop=bool(plan.shouldStop or stop_mpc or stop_cruise), fcw=bool(plan.fcw),
                    allow_throttle=bool(plan.allowThrottle), lateral_accel=cs.vEgo ** 2 * steer * np.pi / 180 / (cp.steerRatio * cp.wheelbase))
      corrected = controller.update(sm, mpc, **kwargs)
      state = controller.state
      counts[state.inhibitionReason] += 1
      if state.active:
        active_sources[str(plan.longitudinalPlanSource)] += 1
        corrections.append(state.appliedCorrection)
        if a_model < 0:
          braking_corrections.append(state.appliedCorrection)
        assert corrected <= min(a_mpc, cruise_accel) + 1e-9
        baseline_errors.append(abs(min(a_model, a_mpc, cruise_accel) - plan.aTarget))
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
