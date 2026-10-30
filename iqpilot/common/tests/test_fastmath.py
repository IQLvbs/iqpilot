import math
import random

import numpy as np

from iqpilot.common.fastmath import clip

SPECIALS = [0.0, -0.0, 1.0, -1.0, 0.5, 1e-300, 1e300, math.inf, -math.inf, math.nan, 4.9e-324, 25.5, -3.5]


def same(a, b):
  if math.isnan(b):
    return math.isnan(a)
  return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)


def test_clip_matches_numpy_on_edge_values():
  for x in SPECIALS:
    for lo in SPECIALS:
      for hi in SPECIALS:
        assert same(float(clip(x, lo, hi)), float(np.clip(x, lo, hi))), (x, lo, hi)


def test_clip_matches_numpy_on_random_values():
  rng = random.Random(1)
  for _ in range(20000):
    x, lo, hi = (rng.uniform(-50, 50) for _ in range(3))
    assert same(float(clip(x, lo, hi)), float(np.clip(x, lo, hi)))


def test_clip_returns_numpy_scalars_like_numpy_does():
  assert type(clip(1.0, 0.0, 2.0)) is type(np.clip(1.0, 0.0, 2.0))
  assert type(clip(np.float64(1.0), 0.0, 2.0)) is type(np.clip(np.float64(1.0), 0.0, 2.0))


def test_gradient_matches_numpy_bit_for_bit():
  from iqpilot.common.fastmath import make_gradient
  from iqpilot.selfdrive.iqmodeld.config import ModelConstants

  t_idxs = np.array(ModelConstants.T_IDXS[:17])
  gradient = make_gradient(t_idxs)
  rng = np.random.default_rng(2)
  for _ in range(2000):
    values = rng.normal(0.0, 3.0, 17)
    assert np.array_equal(gradient(values), np.gradient(values, t_idxs))
  assert np.array_equal(gradient(np.zeros(17)), np.gradient(np.zeros(17), t_idxs))
