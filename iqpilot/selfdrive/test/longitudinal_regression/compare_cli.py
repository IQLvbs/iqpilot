"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import argparse
import json
from pathlib import Path

from iqpilot.selfdrive.test.longitudinal_regression.frames import Frame
from iqpilot.selfdrive.test.longitudinal_regression.metrics import compare


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('baseline', type=Path)
  parser.add_argument('candidate', type=Path)
  parser.add_argument('--out', type=Path, required=True)
  args = parser.parse_args()
  base, cand = json.loads(args.baseline.read_text()), json.loads(args.candidate.read_text())
  result = {name: compare([Frame(**d) for d in base[name]], [Frame(**d) for d in cand[name]]) for name in base if name in cand}
  args.out.write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
  main()
