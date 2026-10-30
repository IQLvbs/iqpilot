"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import json
import os
from pathlib import Path

import numpy as np
import pytest

from iqpilot.selfdrive.test.longitudinal_regression.cli import route_groups
from iqpilot.selfdrive.test.longitudinal_regression.closed_loop import run_windows

CORPUS = os.environ.get('IQ_LONG_CORPUS')
WINDOWS = json.loads((Path(__file__).parent / 'closed_loop_windows.json').read_text())

MIN_GAP_P5 = 1.0
DECEL_LIMIT = 3.6
JERK_P5_LIMIT = -8.0


@pytest.fixture(scope='module')
def results():
  groups = route_groups(Path(CORPUS))
  return run_windows(groups, {name: spans for name, spans in WINDOWS.items() if name in groups})


def test_no_window_ends_in_a_collision(results):
  assert results
  assert not [r for r in results if r['collided']]


def test_gap_at_the_hardest_braking_events(results):
  assert np.percentile([r['min_gap'] for r in results], 5) >= MIN_GAP_P5


def test_braking_stays_inside_actuator_limits(results):
  assert max(r['max_decel'] for r in results) <= DECEL_LIMIT


def test_braking_onset_is_not_abrupt(results):
  assert np.percentile([r['jerk_min'] for r in results], 5) >= JERK_P5_LIMIT
