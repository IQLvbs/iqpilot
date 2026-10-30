"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import time
from types import SimpleNamespace

import numpy as np
import pytest

from iqdbc.car.interfaces import ACCEL_MAX, ACCEL_MIN
from iqpilot.cereal import log
from iqpilot.selfdrive.iqmodeld.config import ModelConstants
from iqpilot.selfdrive.controls.lib.lead_assist.lead_plan import (
  LeadPlan, T_IDXS, get_jerk_factor, get_stopped_equivalence_factor, get_T_FOLLOW,
)
from iqpilot.selfdrive.controls.lib.lead_assist.lead_solver import SOLVE_BUDGET_S, LeadTrajectorySolver
from iqpilot.selfdrive.controls.lib.tests.reference_lead_solver import ReferenceLeadSolver

PERSONALITY = log.LongitudinalPersonality
ANCHOR_TOLERANCE = 0.2

RECORDED_ANCHORS = [
  (29.0, 0.0, 60.0, 22.0, -0.5, PERSONALITY.standard, [0.0, -0.092, -0.341, -0.668, -0.974, -1.177, -1.254, -1.222]),
  (20.0, 0.0, 40.0, 20.0, 0.0, PERSONALITY.standard, [0.0, 0.007, 0.027, 0.054, 0.081, 0.102, 0.111, 0.106]),
  (25.0, 0.5, 120.0, 0.0, 0.0, PERSONALITY.relaxed, [0.5, 0.148, -0.796, -2.014, -3.064, -3.5, -3.5, -3.5]),
  (15.0, -0.5, 30.0, 12.0, -1.0, PERSONALITY.aggressive, [-0.5, -0.515, -0.555, -0.605, -0.647, -0.661, -0.634, -0.565]),
  (8.0, 0.0, 9.0, 0.0, 0.0, PERSONALITY.standard, [0.0, -0.459, -1.615, -2.88, -3.5, -3.425, -2.111, -0.295]),
  (30.0, 0.0, 100.0, 35.0, 0.5, PERSONALITY.standard, [0.0, 0.095, 0.358, 0.724, 1.101, 1.399, 1.546, 1.516]),
  (3.0, 0.0, 6.0, 0.0, 0.0, PERSONALITY.relaxed, [0.0, -0.145, -0.518, -0.955, -1.243, -1.209, -0.812, -0.243]),
  (22.0, -1.0, 35.0, 10.0, -2.0, PERSONALITY.standard, [-1.0, -1.349, -2.221, -3.142, -3.5, -3.5, -3.5, -2.95]),
]


def obstacle(gap, v_lead, a_lead):
  lead_xv = LeadPlan.extrapolate_lead(gap, v_lead, a_lead, 1.5)
  return lead_xv[:, 0] + get_stopped_equivalence_factor(lead_xv[:, 1])


def solve(solver, v_ego, a_ego, x_obstacle, personality):
  return solver.solve(np.array([0.0, v_ego, a_ego]), x_obstacle, get_T_FOLLOW(personality), get_jerk_factor(personality),
                      ACCEL_MIN, ACCEL_MAX)


@pytest.mark.parametrize('v_ego,a_ego,gap,v_lead,a_lead,personality,expected', RECORDED_ANCHORS)
def test_matches_the_recorded_plan(v_ego, a_ego, gap, v_lead, a_lead, personality, expected):
  states, _, _ = solve(LeadTrajectorySolver(T_IDXS), v_ego, a_ego, obstacle(gap, v_lead, a_lead), personality)
  assert np.abs(states[:8, 2] - np.array(expected)).max() < ANCHOR_TOLERANCE


def test_plan_respects_the_actuator_limits():
  solver = LeadTrajectorySolver(T_IDXS)
  states, _, _ = solve(solver, 30.0, 0.0, obstacle(15.0, 0.0, 0.0), PERSONALITY.standard)
  assert states[1:, 2].min() > ACCEL_MIN - 0.05
  assert states[1:, 2].max() < ACCEL_MAX + 0.05
  assert states[:, 1].min() > -0.05


def test_plan_brakes_for_a_stopped_lead_and_stays_behind_it():
  solver = LeadTrajectorySolver(T_IDXS)
  states, _, _ = solve(solver, 25.0, 0.0, obstacle(120.0, 0.0, 0.0), PERSONALITY.standard)
  assert states[:, 2].min() < -1.5
  assert states[-1, 0] < 120.0 - 3.0 + 1.0


def test_plan_holds_speed_at_the_desired_gap():
  v_ego = 20.0
  gap = v_ego * get_T_FOLLOW(PERSONALITY.standard) + 3.0
  states, _, _ = solve(LeadTrajectorySolver(T_IDXS), v_ego, 0.0, obstacle(gap, v_ego, 0.0), PERSONALITY.standard)
  assert np.abs(states[:, 2]).max() < 0.1


def test_warm_start_keeps_the_plan_stable_between_frames():
  solver = LeadTrajectorySolver(T_IDXS)
  x_obstacle = obstacle(60.0, 22.0, -0.5)
  first, _, _ = solve(solver, 29.0, 0.0, x_obstacle, PERSONALITY.standard)
  second, _, _ = solve(solver, 29.0, 0.0, x_obstacle, PERSONALITY.standard)
  assert solver.warm
  assert np.abs(first[:, 2] - second[:, 2]).max() < 0.05


def test_reset_makes_the_next_solve_cold():
  solver = LeadTrajectorySolver(T_IDXS)
  solve(solver, 20.0, 0.0, obstacle(40.0, 20.0, 0.0), PERSONALITY.standard)
  solver.reset()
  assert not solver.warm
  assert not solver.u.any()


@pytest.mark.parametrize('v_ego,a_ego,gap,v_lead,a_lead,personality,expected', RECORDED_ANCHORS)
def test_solve_stays_inside_its_time_budget(v_ego, a_ego, gap, v_lead, a_lead, personality, expected):
  solver = LeadTrajectorySolver(T_IDXS)
  solve(solver, v_ego, a_ego, obstacle(gap, v_lead, a_lead), personality)
  solver.reset()
  started = time.perf_counter()
  solve(solver, v_ego, a_ego, obstacle(gap, v_lead, a_lead), personality)
  assert time.perf_counter() - started < 3 * SOLVE_BUDGET_S


def random_scene(rng):
  v_ego, a_ego = rng.uniform(0, 35), rng.uniform(-2, 1.5)
  x_obstacle = obstacle(rng.uniform(4, 150), rng.uniform(0, 35), rng.uniform(-3, 1))
  personality = rng.choice([PERSONALITY.relaxed, PERSONALITY.standard, PERSONALITY.aggressive])
  return v_ego, a_ego, x_obstacle, personality


def test_native_solver_matches_the_numpy_reference():
  rng = np.random.default_rng(11)
  for _ in range(150):
    native, reference = LeadTrajectorySolver(T_IDXS), ReferenceLeadSolver(T_IDXS)
    v_ego, a_ego, x_obstacle, personality = random_scene(rng)
    for _ in range(6):
      got, _, got_cost = solve(native, v_ego, a_ego, x_obstacle, personality)
      want, _, want_cost = solve(reference, v_ego, a_ego, x_obstacle, personality)
      assert np.abs(got[:, 2] - want[:, 2]).max() < 1e-3
      assert abs(got_cost - want_cost) <= 1e-6 * max(want_cost, 1.0)
      a_ego = float(np.clip(got[1, 2], ACCEL_MIN, ACCEL_MAX))
      v_ego = max(v_ego + a_ego * 0.05, 0.0)


@pytest.mark.parametrize('field', ['x0', 'x_obs', 't_follow', 'jerk_weight', 'a_min', 'a_max'])
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_non_finite_inputs_are_rejected_and_leave_the_solver_untouched(field, bad):
  solver = LeadTrajectorySolver(T_IDXS)
  args = {'x0': np.array([0.0, 20.0, 0.0]), 'x_obs': obstacle(40.0, 20.0, 0.0), 't_follow': 1.45, 'jerk_weight': 1.0,
          'a_min': ACCEL_MIN, 'a_max': ACCEL_MAX}
  solver.solve(**args)
  u_before = solver.u.copy()
  if field in ('x0', 'x_obs'):
    args[field] = args[field].copy()
    args[field][1] = bad
  else:
    args[field] = bad
  states, u, cost = solver.solve(**args)
  assert states is None
  assert not np.isfinite(cost)
  assert np.array_equal(u, u_before)
  assert solver.warm


def test_extreme_inputs_never_raise_and_stay_finite_or_fail_cleanly():
  rng = np.random.default_rng(5)
  solver = LeadTrajectorySolver(T_IDXS)
  magnitudes = [0.0, 1e-12, 1.0, 1e3, 1e8, 1e15, -1.0, -1e8]
  for _ in range(2000):
    x0 = np.array([0.0, rng.choice(magnitudes), rng.choice(magnitudes)])
    x_obstacle = np.sort(rng.choice(magnitudes, T_IDXS.shape[0]))
    if rng.random() < 0.5:
      solver.reset()
    states, u, cost = solver.solve(x0, x_obstacle, get_T_FOLLOW(PERSONALITY.standard), 1.0, ACCEL_MIN, ACCEL_MAX)
    assert np.all(np.isfinite(u))
    if states is not None:
      assert states.shape == (T_IDXS.shape[0], 3)


def test_plan_reports_a_solver_failure_and_keeps_finite_outputs():
  plan = LeadPlan()
  plan.set_cur_state(20.0, 0.0)
  plan.x_obstacle = np.full(T_IDXS.shape[0], np.nan)
  plan.run()
  assert plan.solution_status == 1
  for field in (plan.x_sol, plan.v_solution, plan.a_solution, plan.j_solution):
    assert np.all(np.isfinite(field))
  plan.x_obstacle = obstacle(40.0, 20.0, 0.0)
  plan.run()
  assert plan.solution_status == 0


def braking_model_scene():
  t = np.array(ModelConstants.LEAD_T_IDXS)
  model_lead = SimpleNamespace(prob=0.9, x=40.0 + 20.0 * t - 0.5 * t ** 2, v=20.0 - t)
  radar_lead = SimpleNamespace(status=True, modelProb=0.9, dRel=40.0, vLead=20.0, vRel=-1.0, aLeadK=0.0, aLeadTau=1.5)
  idle_lead = SimpleNamespace(status=False, modelProb=0.0, dRel=0.0, vLead=0.0, vRel=0.0, aLeadK=0.0, aLeadTau=1.5)
  return SimpleNamespace(leadsV3=[model_lead]), SimpleNamespace(leadOne=radar_lead, leadTwo=idle_lead)


def plan_with_toggle(monkeypatch, enabled):
  plan = LeadPlan()
  monkeypatch.setattr(plan, '_read_use_model_lead', lambda: enabled)
  plan.set_cur_state(20.0, 0.0)
  plan.update(*braking_model_scene())
  return plan


def test_new_lead_toggle_switches_between_the_model_and_the_radar_only_lead(monkeypatch):
  model_led = plan_with_toggle(monkeypatch, True)
  radar_only = plan_with_toggle(monkeypatch, False)
  assert model_led.use_model_lead and not radar_only.use_model_lead
  assert model_led.lead_xv_0[-1, 0] < radar_only.lead_xv_0[-1, 0] - 5.0
  assert model_led.lead_xv_0[-1, 1] < radar_only.lead_xv_0[-1, 1] - 5.0
  assert model_led.a_solution[:8].min() < radar_only.a_solution[:8].min()


def test_radar_only_lead_ignores_the_model_lead(monkeypatch):
  plan = plan_with_toggle(monkeypatch, False)
  radar_lead = braking_model_scene()[1].leadOne
  expected = LeadPlan.extrapolate_lead(radar_lead.dRel, radar_lead.vLead, radar_lead.aLeadK, radar_lead.aLeadTau)
  assert np.allclose(plan.lead_xv_0, expected)


def frozen_extrapolate_lead(x_lead, v_lead, a_lead, a_lead_tau):
  from iqpilot.selfdrive.controls.lib.lead_assist.lead_plan import T_DIFFS, T_IDXS
  a_lead_traj = a_lead * np.exp(-a_lead_tau * (T_IDXS**2)/2.)
  v_lead_traj = np.clip(v_lead + np.cumsum(T_DIFFS * a_lead_traj), 0.0, 1e8)
  x_lead_traj = x_lead + np.cumsum(T_DIFFS * v_lead_traj)
  return np.column_stack((x_lead_traj, v_lead_traj))


def test_extrapolate_lead_matches_the_numpy_original_bit_for_bit():
  from iqpilot.selfdrive.controls.lib.lead_assist.lead_plan import LeadPlan
  rng = np.random.default_rng(11)
  specials = [0.0, -0.0, 1e-12, 1e8, 250.0, -10.0, 5.0, np.inf, -np.inf, np.nan]
  cases = [tuple(rng.choice(specials) if rng.random() < 0.15 else rng.uniform(-3, 60) for _ in range(4)) for _ in range(5000)]
  cases += [(float(rng.uniform(1, 150)), float(rng.uniform(0, 40)), float(rng.uniform(-10, 5)), float(rng.uniform(0.2, 4))) for _ in range(5000)]
  with np.errstate(all="ignore"):
    for case in cases:
      expected = frozen_extrapolate_lead(*case)
      actual = LeadPlan.extrapolate_lead(*case)
      assert expected.tobytes() == actual.tobytes(), case


def test_the_fcw_window_is_a_prefix_of_the_plan_horizon():
  from iqpilot.selfdrive.controls.lib.lead_assist.lead_plan import FCW_COUNT, FCW_IDXS
  assert FCW_IDXS[:FCW_COUNT].all() and not FCW_IDXS[FCW_COUNT:].any()
