from numpy import float64


def clip(x, lo, hi):
  if x != x or lo != lo or hi != hi:
    return float64('nan')
  value = lo if x < lo else x
  return float64(hi if value > hi else value)


def make_gradient(coordinates):
  import numpy as np

  coordinates = np.asarray(coordinates, dtype=float)
  spacing = np.diff(coordinates)
  before, after = spacing[:-1], spacing[1:]
  a = -after / (before * (before + after))
  b = (after - before) / (before * after)
  c = before / (after * (before + after))
  first, last = spacing[0], spacing[-1]

  def gradient(values):
    out = np.empty_like(values, dtype=float)
    out[1:-1] = a * values[:-2] + b * values[1:-1] + c * values[2:]
    out[0] = (values[1] - values[0]) / first
    out[-1] = (values[-1] - values[-2]) / last
    return out

  return gradient
