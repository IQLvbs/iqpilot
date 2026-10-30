"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import argparse
import json
from pathlib import Path

from iqpilot.selfdrive.test.longitudinal_regression.frames import Frame
from iqpilot.selfdrive.test.longitudinal_regression.metrics import compare, scorecard
from iqpilot.selfdrive.test.longitudinal_regression.replay import replay_events
from iqpilot.tools.lib.logreader import LogReader

RELEVANT = {
  'initData', 'carParams', 'iqCarParams', 'carState', 'carControl', 'controlsState', 'selfdriveState', 'vehicleParameters',
  'radarState', 'modelV2', 'longitudinalPlan', 'iqCarState', 'iqNavState', 'iqLiveData', 'iqLiveLocation',
  'iqConstructionZone', 'gpsLocation', 'gpsLocationExternal', 'clocks',
}


def make_planner(cp, cp_iq):
  from iqpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
  return LongitudinalPlanner(cp, cp_iq)


def load_events(paths):
  events = []
  for path in paths:
    events.extend(e for e in LogReader(str(path)) if e.which() in RELEVANT)
  return events


def route_groups(root):
  return {d.name: sorted(d.glob('*_rlog.zst'), key=lambda p: int(p.name.split('_')[0])) for d in sorted(root.iterdir()) if d.is_dir()}


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('corpus', type=Path)
  parser.add_argument('--out', type=Path, required=True)
  parser.add_argument('--frames', type=Path)
  parser.add_argument('--against', type=Path)
  parser.add_argument('--routes', nargs='*')
  parser.add_argument('--max-frames', type=int, default=0)
  args = parser.parse_args()
  baseline_frames = json.loads(args.against.read_text()) if args.against else {}
  groups = route_groups(args.corpus)
  result, saved = {}, {}
  for name, logs in groups.items():
    if args.routes and name not in args.routes:
      continue
    frames = replay_events(load_events(logs), make_planner, max_frames=args.max_frames or None)
    saved[name] = [f.to_dict() for f in frames]
    entry = {'segments': len(logs), 'score': scorecard(frames)}
    if name in baseline_frames:
      entry['compare'] = compare([Frame(**d) for d in baseline_frames[name]], frames)
    result[name] = entry
    print(name, entry['score'].get('engaged_frames'), flush=True)
  args.out.parent.mkdir(parents=True, exist_ok=True)
  args.out.write_text(json.dumps(result, indent=2) + '\n')
  if args.frames:
    args.frames.write_text(json.dumps(saved))


if __name__ == '__main__':
  main()
