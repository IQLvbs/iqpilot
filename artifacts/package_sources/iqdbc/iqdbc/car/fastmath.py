import numpy as np

_NUMBERS = (float, np.float64, int)
_NAN = np.float64('nan')


def clip(x, lo, hi):
  kinds = (x.__class__, lo.__class__, hi.__class__)
  if any(kind not in _NUMBERS for kind in kinds) or all(kind is int for kind in kinds):
    return np.clip(x, lo, hi)
  if x != x or lo != lo or hi != hi:
    return _NAN
  value = lo if x < lo else x
  return np.float64(hi if value > hi else value)
