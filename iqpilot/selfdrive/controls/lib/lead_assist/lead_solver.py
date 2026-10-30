import ctypes
from pathlib import Path

import numpy as np

COMFORT_BRAKE = 2.5
STOP_DISTANCE = 3.0
SOLVE_BUDGET_S = 0.015

LIBRARY_PATH = Path(__file__).with_name('libleadsolver.so')


def _load_library():
  lib = ctypes.CDLL(str(LIBRARY_PATH))
  lib.lead_solver_new.restype = ctypes.c_void_p
  lib.lead_solver_new.argtypes = [ctypes.c_void_p, ctypes.c_int]
  lib.lead_solver_free.restype = None
  lib.lead_solver_free.argtypes = [ctypes.c_void_p]
  lib.lead_solver_solve.restype = ctypes.c_int
  lib.lead_solver_solve.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double, ctypes.c_double, ctypes.c_double,
    ctypes.c_double, ctypes.c_int, ctypes.c_double, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
  ]
  return lib


_lib = _load_library()


class LeadTrajectorySolver:
  def __init__(self, t_idxs):
    self.t_idxs = np.ascontiguousarray(t_idxs, dtype=np.float64)
    self.n = len(self.t_idxs) - 1
    self._handle = _lib.lead_solver_new(self.t_idxs.ctypes.data, self.n)
    if not self._handle:
      raise ValueError(f"unsupported lead solver horizon of {self.n} nodes")
    self._x0 = np.zeros(3)
    self._x_obs = np.zeros(self.n + 1)
    self._cost = np.zeros(1)
    self._scratch_u = np.zeros(self.n)
    self.reset()

  def __del__(self):
    handle = getattr(self, '_handle', None)
    if handle:
      _lib.lead_solver_free(handle)
      self._handle = None

  def reset(self):
    self.u = np.zeros(self.n)
    self.warm = False

  def solve(self, x0, x_obs, t_follow, jerk_weight, a_min, a_max):
    self._x0[:] = x0
    self._x_obs[:] = x_obs
    self._scratch_u[:] = self.u
    states = np.empty((self.n + 1, 3))
    status = _lib.lead_solver_solve(
      self._handle, self._x0.ctypes.data, self._x_obs.ctypes.data, t_follow, jerk_weight, a_min, a_max,
      int(self.warm), SOLVE_BUDGET_S, self._scratch_u.ctypes.data, states.ctypes.data, self._cost.ctypes.data,
    )
    if status != 0:
      return None, self.u, float('inf')
    self.u = self._scratch_u.copy()
    self.warm = True
    return states, self.u, float(self._cost[0])
