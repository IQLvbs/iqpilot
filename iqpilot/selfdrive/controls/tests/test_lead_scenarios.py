"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import itertools

import numpy as np
import pytest

from iqpilot.cereal import log
from iqpilot.selfdrive.controls.lib.lead_assist.lead_assist import SAFE_TIME_GAP_FRACTION
from iqpilot.selfdrive.controls.lib.lead_assist.lead_plan import get_T_FOLLOW
from iqpilot.selfdrive.test.longitudinal_maneuvers.scenarios import COLLISION_GAP, MAX_BRAKE, Scenario, avoidable, run, stopping_distance

PERSONALITIES = [0, 1, 2]
MODELS = ['follow', 'blind']


def ramp(t0, t1, v0, v1):
  return lambda t: float(np.interp(t, [t0, t1], [v0, v1]))


@pytest.mark.parametrize('model,personality,speed,margin', itertools.product(MODELS, PERSONALITIES, [8.0, 15.0, 22.0, 30.0], [1.15, 1.6, 2.5]))
def test_stopped_lead_approach(model, personality, speed, margin):
  gap = stopping_distance(speed, 3.0) * margin + 4.0
  out = run(Scenario(speed, gap, lambda t: 0.0, 20.0 + 2.0 * speed, model, personality))
  assert out.min_gap > COLLISION_GAP
  assert out.max_decel <= MAX_BRAKE + 0.05
  assert out.final_speed < 0.5


@pytest.mark.parametrize('model,personality,speed,lead_decel', itertools.product(MODELS, PERSONALITIES, [10.0, 20.0, 30.0], [1.0, 2.0, 3.0, 4.5]))
def test_lead_brakes_to_a_stop(model, personality, speed, lead_decel):
  gap = (0.65 if model == 'blind' else 1.3) * 1.45 * speed + 4.0
  t_stop = speed / lead_decel
  scenario = Scenario(speed, gap, lambda t: max(speed - lead_decel * max(t - 8.0, 0.0), 0.0), 8.0 + t_stop + 12.0, model, personality)
  out = run(scenario)
  if avoidable(speed, gap, speed, lead_decel):
    assert out.min_gap > COLLISION_GAP
  assert out.max_decel <= MAX_BRAKE + 0.05


@pytest.mark.parametrize('model,personality,speed,cut_gap,lead_speed', itertools.product(MODELS, PERSONALITIES, [15.0, 25.0], [12.0, 25.0, 45.0], [6.0, 12.0]))
def test_cut_in_of_a_slower_vehicle(model, personality, speed, cut_gap, lead_speed):
  scenario = Scenario(speed, cut_gap, lambda t: lead_speed, 25.0, model, personality, lead_visible=lambda t: 0.0 if t < 3.0 else 1.0)
  out = run(scenario)
  if avoidable(speed, cut_gap - speed * 0.0, lead_speed):
    assert out.min_gap > COLLISION_GAP
  assert out.max_decel <= MAX_BRAKE + 0.05


@pytest.mark.parametrize('model,personality', itertools.product(MODELS, PERSONALITIES))
def test_resumes_when_the_lead_drives_off(model, personality):
  scenario = Scenario(0.0, 4.5, lambda t: float(np.interp(t, [5.0, 12.0], [0.0, 8.0])), 40.0, model, personality)
  out = run(scenario)
  assert out.started
  assert out.min_gap > COLLISION_GAP
  assert out.final_speed > 3.0


@pytest.mark.parametrize('model,personality', itertools.product(MODELS, PERSONALITIES))
def test_stop_and_go_traffic(model, personality):
  period = 24.0

  def lead(t):
    return float(np.interp(t % period, [0.0, 6.0, 10.0, 16.0, 20.0, period], [0.0, 0.0, 8.0, 8.0, 0.0, 0.0]))

  out = run(Scenario(0.0, 5.0, lead, 120.0, model, personality))
  assert out.min_gap > COLLISION_GAP
  assert out.max_decel <= MAX_BRAKE + 0.05
  assert out.max_accel <= 2.05


@pytest.mark.parametrize('personality', PERSONALITIES)
def test_flickering_lead_detection_with_a_lead_aware_model(personality):
  def flicker(t):
    return 1.0 if int(t * 2) % 3 else 0.0

  out = run(Scenario(20.0, 45.0, lambda t: 18.0, 30.0, 'follow', personality, lead_visible=flicker))
  assert out.min_gap > COLLISION_GAP
  assert out.max_decel <= MAX_BRAKE + 0.05
  assert np.isfinite(out.jerk_p99)


@pytest.mark.parametrize('personality', PERSONALITIES)
def test_flickering_lead_detection_keeps_the_planner_finite_with_a_blind_model(personality):
  def flicker(t):
    return 1.0 if int(t * 2) % 3 else 0.0

  out = run(Scenario(20.0, 45.0, lambda t: 18.0, 30.0, 'blind', personality, lead_visible=flicker))
  assert np.isfinite(out.min_gap)
  assert out.max_decel <= MAX_BRAKE + 0.05
  assert out.max_accel <= 2.05


@pytest.mark.parametrize('personality,speed', itertools.product(PERSONALITIES, [10.0, 20.0, 30.0]))
def test_assist_is_transparent_behind_a_lead_aware_model(personality, speed):
  out = run(Scenario(speed, 3.5 + 1.3 * speed, lambda t: speed, 60.0, 'follow', personality))
  assert out.assist_frames == 0
  assert out.fcw_frames == 0


@pytest.mark.parametrize('personality,speed', itertools.product(PERSONALITIES, [10.0, 20.0, 30.0]))
def test_blind_model_following_stays_comfortable(personality, speed):
  out = run(Scenario(speed, 3.5 + 1.3 * speed, lambda t: speed, 60.0, 'blind', personality))
  assert out.min_gap > 0.4 * speed
  assert out.max_decel < 2.0
  assert out.fcw_frames == 0


PERSONALITY_ENUM = [log.LongitudinalPersonality.aggressive, log.LongitudinalPersonality.standard, log.LongitudinalPersonality.relaxed]


@pytest.mark.parametrize('personality,speed,lead_decel', itertools.product(PERSONALITIES, [15.0, 25.0], [2.0, 3.0]))
def test_personality_floor_is_held_when_a_blind_model_meets_a_braking_lead(personality, speed, lead_decel):
  floor = SAFE_TIME_GAP_FRACTION * get_T_FOLLOW(PERSONALITY_ENUM[personality])
  gap = 0.7 * get_T_FOLLOW(PERSONALITY_ENUM[personality]) * speed + 4.0
  def lead(t):
    return max(speed - lead_decel * max(t - 8.0, 0.0), 0.0)

  out = run(Scenario(speed, gap, lead, 8.0 + speed / lead_decel + 10.0, 'blind', personality))
  assert out.min_time_gap >= 0.9 * floor
  assert out.min_gap > COLLISION_GAP
