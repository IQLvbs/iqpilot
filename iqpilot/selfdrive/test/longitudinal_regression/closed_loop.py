"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import argparse
import json
from pathlib import Path

import numpy as np

from iqpilot.cereal import custom
from iqpilot.common.prefix import OpenpilotPrefix
from iqpilot.common.realtime import DT_MDL
from iqpilot.selfdrive.test.longitudinal_regression.cli import load_events, make_planner, route_groups
from iqpilot.selfdrive.test.longitudinal_regression.replay import _apply_params, _recorded_params, replay_events
from iqpilot.selfdrive.test.longitudinal_regression.replay_state import ReplayState

ACTUATOR_DELAY_S = 0.3
ACTUATOR_TAU_S = 0.25
WARMUP_S = 2.0
COLLISION_GAP = 0.4
WINDOW_BEFORE_S = 6.0
WINDOW_AFTER_S = 14.0
EVENT_BRAKE = -1.2




def _builder(message):
  try:
    return message.as_builder()
  except AttributeError:
    return message


def _setup(events):
  recorded, cp, cp_iq = {}, None, None
  for event in events:
    kind = event.which()
    if kind == 'initData' and not recorded:
      recorded = _recorded_params(event)
    elif kind == 'carParams' and cp is None:
      cp = event.carParams
    elif kind == 'iqCarParams' and cp_iq is None:
      cp_iq = event.iqCarParams
  return recorded, cp, cp_iq or custom.IQCarParams.new_message()


def simulate_window(events, t_start, t_end, make_planner_fn):
  events = sorted(events, key=lambda e: e.logMonoTime)
  first = next(e.logMonoTime for e in events if e.which() == 'modelV2')
  with OpenpilotPrefix():
    recorded, cp, cp_iq = _setup(events)
    _apply_params(recorded, {})
    planner = make_planner_fn(cp, cp_iq)
    sm = ReplayState()
    x_ego_rec = 0.0
    x_ego, v_ego, a_actual = None, None, 0.0
    command_queue = []
    gaps, accels, jerks = [], [], []
    last_a = None
    prev_model_t = None
    for event in events:
      kind = event.which()
      sm.feed(event)
      if kind != 'modelV2':
        continue
      t = (event.logMonoTime - first) * 1e-9
      dt = DT_MDL if prev_model_t is None else min(max(t - prev_model_t, 0.0), 0.1)
      prev_model_t = t
      required = {'carState', 'controlsState', 'selfdriveState', 'radarState'}
      if not required.issubset(sm.seen) or t < t_start - WARMUP_S:
        continue
      cs_rec = sm['carState']
      x_ego_rec += float(cs_rec.vEgo) * dt
      lead = sm['radarState'].leadOne
      lead_abs = x_ego_rec + float(lead.dRel) if lead.status else None
      closed = t >= t_start
      if closed and x_ego is None:
        x_ego, v_ego = x_ego_rec, float(cs_rec.vEgo)
        a_actual = float(cs_rec.aEgo)
      if closed:
        cs = _builder(cs_rec)
        cs.vEgo = float(v_ego)
        cs.aEgo = float(a_actual)
        cs.standstill = bool(v_ego < 0.05)
        sm['carState'] = cs
        if lead_abs is not None:
          rs = _builder(sm['radarState'])
          rs.leadOne.dRel = float(lead_abs - x_ego)
          rs.leadOne.vRel = float(lead.vLead - v_ego)
          sm['radarState'] = rs
      sm.frame += 1
      planner.update(sm)
      a_cmd = float(planner.output_a_target)
      if planner.output_should_stop:
        a_cmd = min(a_cmd, -0.5)
      if closed:
        command_queue.append(a_cmd)
        delayed = command_queue.pop(0) if len(command_queue) > int(ACTUATOR_DELAY_S / DT_MDL) else 0.0
        a_actual += (delayed - a_actual) * dt / ACTUATOR_TAU_S
        v_next = max(v_ego + a_actual * dt, 0.0)
        if v_next == 0.0:
          a_actual = max(a_actual, 0.0)
        x_ego += 0.5 * (v_ego + v_next) * dt
        v_ego = v_next
        if lead_abs is not None:
          gaps.append(lead_abs - x_ego)
        accels.append(a_actual)
        if last_a is not None:
          jerks.append((a_actual - last_a) / dt if dt > 0 else 0.0)
        last_a = a_actual
      if t >= t_end:
        break
  if not gaps:
    return None
  return dict(min_gap=float(min(gaps)), max_decel=float(-min(accels)), jerk_min=float(min(jerks)) if jerks else 0.0,
              collided=bool(min(gaps) < COLLISION_GAP), frames=len(accels), final_gap=float(gaps[-1]))


def event_windows(frames, max_windows):
  t = np.array([f.t for f in frames])
  recorded = np.array([f.recorded_a for f in frames])
  braking = np.array([f.lead_status and f.long_active and f.enabled for f in frames]) & (recorded < EVENT_BRAKE)
  windows, last_end = [], -1e9
  for i in np.flatnonzero(braking):
    if t[i] < last_end:
      continue
    windows.append((max(t[i] - WINDOW_BEFORE_S, 0.0), t[i] + WINDOW_AFTER_S))
    last_end = windows[-1][1]
    if len(windows) >= max_windows:
      break
  return windows


def run_windows(groups, windows):
  results = []
  for name, spans in windows.items():
    events = load_events(groups[name])
    for t0, t1 in spans:
      outcome = simulate_window(events, t0 + WINDOW_BEFORE_S - 3.0, t1, make_planner)
      if outcome:
        results.append({'route': name, 't0': t0, **outcome})
  return results


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('corpus', type=Path)
  parser.add_argument('--windows', type=Path, required=True)
  parser.add_argument('--discover', type=int, default=0)
  parser.add_argument('--out', type=Path, required=True)
  args = parser.parse_args()
  groups = route_groups(args.corpus)
  if args.discover:
    windows = {name: event_windows(replay_events(load_events(logs), make_planner), args.discover) for name, logs in groups.items()}
    args.windows.write_text(json.dumps({k: v for k, v in windows.items() if v}, indent=1) + '\n')
  windows = json.loads(args.windows.read_text())
  results = run_windows(groups, windows)
  args.out.write_text(json.dumps(results, indent=2) + '\n')
  print(len(results), 'windows')


if __name__ == '__main__':
  main()
