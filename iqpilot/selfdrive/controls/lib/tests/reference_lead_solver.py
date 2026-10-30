import time

import numpy as np

from iqpilot.selfdrive.controls.lib.lead_assist.lead_solver import COMFORT_BRAKE, SOLVE_BUDGET_S, STOP_DISTANCE

X_EGO_OBSTACLE_COST = 3.0
J_EGO_COST = 20.0
DANGER_ZONE_COST = 100.0
LIMIT_COST = 1e6
LEAD_DANGER_FACTOR = 0.75
ACTIVE_SET_PASSES = 12
BACKTRACKS = 8
RAMP_TIME = 1.5
RAMP_TARGETS = (0.0,)
WARM_ITERATIONS = 3
COLD_ITERATIONS = 12
CONVERGED_DROP = 1e-7


class ReferenceLeadSolver:
  def __init__(self, t_idxs):
    self.n = len(t_idxs) - 1
    self.t_idxs = np.asarray(t_idxs, dtype=float)
    dts = np.diff(self.t_idxs)
    self.phi = np.zeros((self.n + 1, 3, 3))
    self.gamma = np.zeros((self.n + 1, 3, self.n))
    self.phi[0] = np.eye(3)
    for k, dt in enumerate(dts):
      f = np.array([[1.0, dt, dt * dt / 2.0], [0.0, 1.0, dt], [0.0, 0.0, 1.0]])
      g = np.array([dt ** 3 / 6.0, dt * dt / 2.0, dt])
      self.phi[k + 1] = f @ self.phi[k]
      self.gamma[k + 1] = f @ self.gamma[k]
      self.gamma[k + 1, :, k] = g
    self.stage_scale = np.sqrt(dts)
    self.node_scale = np.append(self.stage_scale, 1.0)
    self.phi_flat = self.phi.reshape(-1, 3)
    self.gamma_flat = self.gamma.reshape(-1, self.n)
    self.gx, self.gv, self.ga = self.gamma[:, 0, :], self.gamma[:, 1, :], self.gamma[:, 2, :]
    self.inner = np.arange(1, self.n)
    self.diag_index = np.diag_indices(self.n)
    self.weights = np.concatenate([
      np.full(3 * (self.n - 1), LIMIT_COST * 1.0),
      np.full(self.n - 1, DANGER_ZONE_COST * 1.0),
    ]) * np.tile(self.stage_scale[self.inner] ** 2, 4)
    self.gx_tail, self.gv_tail = self.gx[1:], self.gv[1:]
    self.gx_inner, self.gv_inner, self.ga_inner = self.gx[self.inner], self.gv[self.inner], self.ga[self.inner]
    self.eye = np.eye(self.n)
    self.reset()

  def reset(self):
    self.u = np.zeros(self.n)
    self.warm = False

  def states(self, x0, u):
    return (self.phi_flat @ x0 + self.gamma_flat @ u).reshape(-1, 3)

  def residuals(self, u, x0, x_obs, t_follow, jerk_weight, a_min, a_max):
    inner = self.inner
    s = self.states(x0, u)
    x, v, a = s[:, 0], s[:, 1], s[:, 2]
    d = np.maximum(v + 10.0, 1.0)
    desired = v * v / (2 * COMFORT_BRAKE) + t_follow * v + STOP_DISTANCE
    gap = x_obs - x
    e = (gap - desired) / d
    danger = (gap - LEAD_DANGER_FACTOR * desired) / d
    wx = np.sqrt(X_EGO_OBSTACLE_COST) * self.node_scale[1:]
    wj = np.sqrt(J_EGO_COST * jerk_weight) * self.stage_scale
    r_s = np.concatenate([wx * e[1:], wj * u])
    h = np.concatenate([v[inner], a[inner] - a_min, a_max - a[inner], danger[inner]])
    return r_s, h, (v, d, e, danger, wx, wj, s)

  def jacobians(self, aux, t_follow):
    v, d, e, danger, wx, wj, _ = aux
    ddes = v / COMFORT_BRAKE + t_follow
    de_dx = -1.0 / d
    de_dv = (-ddes - e) / d
    dh_dv = (-LEAD_DANGER_FACTOR * ddes - danger) / d
    inner = self.inner
    j_s = np.zeros((2 * self.n, self.n))
    j_s[:self.n] = wx[:, None] * (de_dx[1:, None] * self.gx_tail + de_dv[1:, None] * self.gv_tail)
    j_s[self.n:][self.diag_index] = wj
    m = self.n - 1
    h_jac = np.empty((4 * m, self.n))
    h_jac[:m] = self.gv_inner
    h_jac[m:2 * m] = self.ga_inner
    h_jac[2 * m:3 * m] = -self.ga_inner
    h_jac[3 * m:] = de_dx[inner, None] * self.gx_inner + dh_dv[inner, None] * self.gv_inner
    return j_s, h_jac

  def cost(self, r_s, h):
    return 0.5 * (r_s @ r_s + self.weights @ np.minimum(h, 0.0) ** 2)

  def step(self, r_s, j_s, h, h_jac):
    gradient_base = j_s.T @ r_s
    curvature_base = j_s.T @ j_s
    active = h < 0.0
    for _ in range(ACTIVE_SET_PASSES):
      w = self.weights * active
      lhs = curvature_base + h_jac.T @ (w[:, None] * h_jac)
      rhs = -gradient_base - h_jac.T @ (w * h)
      delta = np.linalg.solve(lhs + 1e-9 * self.eye, rhs)
      now_active = h + h_jac @ delta < 0.0
      if np.array_equal(now_active, active):
        break
      active = now_active
    return delta

  def refine(self, u, x0, x_obs, t_follow, jerk_weight, a_min, a_max, iterations, deadline=float('inf')):
    args = (x0, x_obs, t_follow, jerk_weight, a_min, a_max)
    r_s, h, aux = self.residuals(u, *args)
    cost = self.cost(r_s, h)
    for _ in range(iterations):
      if time.perf_counter() > deadline:
        break
      j_s, h_jac = self.jacobians(aux, t_follow)
      delta = self.step(r_s, j_s, h, h_jac)
      scale = 1.0
      for _ in range(BACKTRACKS):
        trial = self.residuals(u + scale * delta, *args)
        trial_cost = self.cost(trial[0], trial[1])
        if trial_cost < cost:
          break
        scale *= 0.5
      else:
        break
      u = u + scale * delta
      r_s, h, aux = trial
      converged = cost - trial_cost < CONVERGED_DROP * max(trial_cost, 1.0)
      cost = trial_cost
      if converged:
        break
    return aux[6], u, cost

  def ramp_guess(self, a0, a_target):
    a_profile = a0 + (a_target - a0) * np.minimum(self.t_idxs / RAMP_TIME, 1.0)
    return np.diff(a_profile) / np.diff(self.t_idxs)

  def solve(self, x0, x_obs, t_follow, jerk_weight, a_min, a_max):
    if self.warm:
      starts, iterations = [self.u], WARM_ITERATIONS
    else:
      starts, iterations = [self.u] + [self.ramp_guess(x0[2], a) for a in RAMP_TARGETS], COLD_ITERATIONS
    best = None
    deadline = time.perf_counter() + SOLVE_BUDGET_S
    for u0 in starts:
      result = self.refine(u0, x0, x_obs, t_follow, jerk_weight, a_min, a_max, iterations, deadline)
      if best is None or result[2] < best[2]:
        best = result
    self.u = best[1]
    self.warm = True
    return best
