import math
import numpy as np

from iqdbc.car.fastmath import clip

SPECIALS = [0.0, -0.0, 1.0, -1.0, 0.5, 1e-300, 1e300, math.inf, -math.inf, math.nan, 25.5, -3.5, 3, -2, 0]


def same(a, b):
  a, b = float(a), float(b)
  if math.isnan(b):
    return math.isnan(a)
  return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)


def test_clip_matches_numpy_on_edge_values():
  for x in SPECIALS:
    for lo in SPECIALS:
      for hi in SPECIALS:
        got, want = clip(x, lo, hi), np.clip(x, lo, hi)
        assert same(got, want), (x, lo, hi)
        assert type(got) is type(want), (x, lo, hi, type(got), type(want))


def test_clip_defers_to_numpy_for_other_types():
  assert type(clip(np.float32(1.5), 0.0, 2.0)) is type(np.clip(np.float32(1.5), 0.0, 2.0))
  assert np.array_equal(clip(np.array([1.0, 5.0]), 0.0, 2.0), np.clip(np.array([1.0, 5.0]), 0.0, 2.0))
