"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import math
import random

import numpy as np

from iqpilot.cereal import log, messaging
from iqpilot.common.realtime import DT_MDL
from iqpilot.selfdrive.controls.lib.lead_assist.lead_assist import LeadAssist, _gap_slope, required_decel, required_decel_scalar

STANDARD = log.LongitudinalPersonality.standard
ACTION_T = 0.35


def make_sm(v_ego, lead_d=None, lead_v=0.0, lead_a=0.0):
  sm = {name: getattr(messaging.new_message(name), name) for name in ('radarState', 'carState', 'modelV2')}
  sm['carState'].vEgo = float(v_ego)
  sm['carState'].standstill = v_ego < 0.01
  lead = sm['radarState'].leadOne
  if lead_d is not None:
    lead.status = True
    lead.dRel = float(lead_d)
    lead.vLead = lead.vLeadK = float(lead_v)
    lead.vRel = float(lead_v - v_ego)
    lead.aLeadK = float(lead_a)
    lead.aLeadTau = 1.5
    lead.modelProb = 1.0
  sm['modelV2'].init('leadsV3', 3)
  return sm


def run(assist, v_ego, lead_d, lead_v, a_model, steps, engaged=True):
  out = None
  a_desired = 0.0
  for _ in range(steps):
    out = assist.update(make_sm(v_ego, lead_d, lead_v), v_ego, a_desired, a_model, STANDARD, ACTION_T, engaged)
    a_desired = out.a_target if out.a_target is not None else 0.0
  return out


def test_idle_without_lead():
  out = run(LeadAssist(DT_MDL, 0.25), 20.0, None, 0.0, 0.5, 10)
  assert out.a_target is None
  assert not out.active
  assert not out.fcw
  assert out.a_ref is None


def test_engages_when_model_ignores_a_stopped_lead():
  assist = LeadAssist(DT_MDL, 0.25)
  out = run(assist, 25.0, 120.0, 0.0, 0.5, 10)
  assert out.active
  assert out.a_target < -1.0
  assert out.a_target < -1.0


def test_brakes_past_the_requirement_when_the_need_is_serious():
  need = float(required_decel(15.0, 54.0, 0.0, 0.0))
  assert 2.0 < need < 2.5
  out = run(LeadAssist(DT_MDL, 0.25), 15.0, 54.0, 0.0, 0.5, 60)
  assert out.active
  assert out.a_target <= -1.1 * need


def test_a_lagging_lead_speed_is_overruled_by_the_closing_gap():
  assist = LeadAssist(DT_MDL, 0.25)
  v_ego, gap, speed = 28.0, 80.0, None
  for _ in range(40):
    gap -= (v_ego - 15.0) * DT_MDL
    speed = assist._gap_rate_lead_speed(gap, v_ego, 25.0)
  assert abs(speed - 15.0) < 0.5


def test_a_consistent_lead_speed_is_left_alone():
  assist = LeadAssist(DT_MDL, 0.25)
  v_ego, gap, speed = 28.0, 80.0, None
  for _ in range(40):
    gap -= (v_ego - 20.0) * DT_MDL
    speed = assist._gap_rate_lead_speed(gap, v_ego, 20.0)
  assert abs(speed - 20.0) < 0.3


def test_gap_rate_is_ignored_at_crawling_speed():
  assist = LeadAssist(DT_MDL, 0.25)
  speed = None
  for i in range(40):
    speed = assist._gap_rate_lead_speed(10.0 - 0.1 * i, 2.0, 1.0)
  assert speed == 1.0


def test_stays_out_of_the_way_when_the_model_is_already_braking():
  assist = LeadAssist(DT_MDL, 0.25)
  out = run(assist, 25.0, 120.0, 0.0, -2.5, 20)
  assert not out.active
  assert out.a_target is None


def test_transparent_at_a_comfortable_following_gap():
  assist = LeadAssist(DT_MDL, 0.25)
  out = run(assist, 20.0, 45.0, 20.0, 0.1, 40)
  assert not out.active


def test_enforces_the_time_gap_floor_against_a_model_that_keeps_closing():
  assist = LeadAssist(DT_MDL, 0.25)
  out = run(assist, 20.0, 10.0, 20.0, 0.3, 10)
  assert out.active


def test_not_engaged_planner_never_activates():
  assist = LeadAssist(DT_MDL, 0.25)
  out = run(assist, 25.0, 60.0, 0.0, 0.5, 20, engaged=False)
  assert not out.active


def test_holds_a_stopped_lead_at_low_speed():
  assist = LeadAssist(DT_MDL, 0.25)
  out = run(assist, 0.0, 3.0, 0.0, 0.6, 10)
  assert out.active
  assert out.should_stop


def test_releases_after_the_lead_leaves():
  assist = LeadAssist(DT_MDL, 0.25)
  assert run(assist, 25.0, 60.0, 0.0, 0.5, 10).active
  out = run(assist, 25.0, None, 0.0, 0.5, 1)
  assert not out.active
  assert not assist.active


def test_trajectories_have_control_horizon_length():
  assist = LeadAssist(DT_MDL, 0.25)
  run(assist, 20.0, 40.0, 20.0, 0.0, 5)
  assert len(assist.a_trajectory) == len(assist.v_trajectory) == len(assist.j_trajectory)
  assert np.all(np.isfinite(assist.v_trajectory))


def same_float(a, b):
  return (math.isnan(a) and math.isnan(b)) or (a == b and math.copysign(1.0, a) == math.copysign(1.0, b))


def test_scalar_required_decel_matches_the_array_version_bit_for_bit():
  rng = random.Random(7)
  specials = [0.0, -0.0, 0.3, 3.0, 3.5, 0.5, 1e-9, 250.0, math.inf, -math.inf, math.nan]
  for _ in range(20000):
    values = [rng.choice(specials) if rng.random() < 0.15 else rng.uniform(-5.0, 60.0) for _ in range(4)]
    with np.errstate(all="ignore"):
      expected = float(required_decel(*values))
    actual = required_decel_scalar(*values)
    assert same_float(expected, actual), values


def test_gap_slope_matches_polyfit_bit_for_bit():
  rng = np.random.default_rng(3)
  for count in (10, 31):
    for _ in range(300):
      gaps = np.array([float(g) for g in (40.0 + np.cumsum(rng.normal(scale=0.2, size=count)))])
      expected = np.polyfit(np.arange(count) * DT_MDL, gaps, 1)[0]
      assert _gap_slope(gaps, DT_MDL) == expected


def test_personality_index_is_clamped_like_numpy_clip():
  for raw in (-3, -1, 0, 1, 2, 3, 7):
    assert min(max(raw, 0), 2) == int(np.clip(raw, 0, 2))
