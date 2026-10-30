import math
import random

import numpy as np
import pytest

from iqpilot.selfdrive.iqlocd.models.constants import ObservationKind
from iqpilot.selfdrive.locationd.locationd import _norm
from iqpilot.selfdrive.locationd.models.pose_kf import PoseKalman

KINDS = (ObservationKind.PHONE_GYRO, ObservationKind.PHONE_ACCEL, ObservationKind.CAMERA_ODO_ROTATION,
         ObservationKind.CAMERA_ODO_TRANSLATION)


def same(a, b):
  return np.array_equal(np.asarray(a), np.asarray(b), equal_nan=True)


def make_filters():
  filters = []
  for _ in range(2):
    kf = PoseKalman(0.8)
    kf.init_state(PoseKalman.initial_x, PoseKalman.initial_P, 100.0)
    filters.append(kf)
  return filters


@pytest.mark.parametrize("seed", range(6))
def test_observe_matches_predict_and_observe(seed):
  rng = random.Random(seed)
  full, lean = make_filters()
  now = 100.0
  for step in range(600):
    now += rng.choice([0.005, 0.01, 0.01, 0.02])
    jitter = rng.choice([0.0, 0.0, -0.004, -0.02, -0.3, -1.5])
    kind = rng.choice(KINDS)
    measurement = np.array([rng.gauss(0, 0.5) for _ in range(3)])
    if step == 400:
      measurement[1] = math.nan
    if step < 20:
      jitter = 0.0
    try:
      a = full.predict_and_observe(now + jitter, kind, measurement)
    except ValueError:
      with pytest.raises(ValueError):
        lean.observe(now + jitter, kind, measurement)
      continue
    b = lean.observe(now + jitter, kind, measurement)
    assert (a is None) == (b is None)
    if a is not None:
      innovations, finite = b
      assert len(innovations) == len(a[6])
      assert all(same(x, y) for x, y in zip(innovations, a[6], strict=True))
      assert finite == bool(np.isfinite(a[1]).all() and np.isfinite(a[3]).all())
    assert same(full.x, lean.x)
    assert same(full.P, lean.P)
    assert full.t == lean.t or (math.isnan(full.t) and math.isnan(lean.t))


def test_x_view_reflects_the_filter_state_without_copying():
  kf, _ = make_filters()
  view = kf.x_view
  assert same(view, kf.x)
  kf.observe(100.01, ObservationKind.PHONE_GYRO, np.array([0.1, 0.2, 0.3]))
  assert same(kf.x_view, kf.x)


@pytest.mark.parametrize("seed", range(4))
def test_norm_matches_numpy(seed):
  rng = np.random.default_rng(seed)
  vectors = [rng.normal(size=3) * 10.0 ** rng.integers(-6, 6) for _ in range(500)]
  vectors += [np.array([math.nan, 1.0, 2.0]), np.array([math.inf, 0.0, 0.0]), np.zeros(3), np.array([1e200, 1e200, 1e200])]
  for vector in vectors:
    with np.errstate(all="ignore"):
      expected = np.linalg.norm(vector)
      actual = _norm(vector)
    assert (math.isnan(expected) and math.isnan(actual)) or expected == actual
