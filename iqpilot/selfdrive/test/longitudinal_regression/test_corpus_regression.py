"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import json
import os
from pathlib import Path

import pytest

from iqpilot.selfdrive.test.longitudinal_regression.cli import load_events, make_planner, route_groups
from iqpilot.selfdrive.test.longitudinal_regression.metrics import scorecard
from iqpilot.selfdrive.test.longitudinal_regression.replay import replay_events

CORPUS = os.environ.get('IQ_LONG_CORPUS')
BASELINES = json.loads((Path(__file__).parent / 'baseline_scorecards.json').read_text())

LEAD_BOUND_SHARE_MAX = 0.35
ROUTE_DEFICIT_RATIO = 1.5
ROUTE_DEFICIT_SLACK_FRAMES = 20
FCW_SLACK_FRAMES = 2
BRAKE_P1_SLACK = 2.0
JERK_P1_SLACK = 2.5


@pytest.fixture(scope='module')
def scores():
  groups = route_groups(Path(CORPUS))
  return {name: scorecard(replay_events(load_events(groups[name]), make_planner)) for name in BASELINES if name in groups}


@pytest.mark.parametrize('route', sorted(BASELINES))
def test_route_does_not_regress(scores, route):
  if route not in scores:
    pytest.skip(f'{route} is not in the corpus')
  base, score = BASELINES[route], scores[route]
  assert score['engaged_frames'] == base['engaged_frames']
  assert score['replayed_lead_bound_frames'] <= LEAD_BOUND_SHARE_MAX * score['engaged_frames']
  assert score['deficit_frames'] <= ROUTE_DEFICIT_RATIO * base['deficit_frames'] + ROUTE_DEFICIT_SLACK_FRAMES
  assert score['fcw_frames'] <= base['fcw_frames'] + FCW_SLACK_FRAMES
  assert score['a_target_p1'] >= base['a_target_p1'] - BRAKE_P1_SLACK
  assert score['jerk_p1'] >= base['jerk_p1'] - JERK_P1_SLACK


def test_corpus_wide_braking_coverage_beats_the_old_planner(scores):
  assert sum(s['deficit_frames'] for s in scores.values()) <= sum(BASELINES[n]['deficit_frames'] for n in scores)


def test_model_drives_the_vast_majority_of_the_corpus(scores):
  lead_bound = sum(s['replayed_lead_bound_frames'] for s in scores.values())
  engaged = sum(s['engaged_frames'] for s in scores.values())
  assert lead_bound <= 0.1 * engaged
