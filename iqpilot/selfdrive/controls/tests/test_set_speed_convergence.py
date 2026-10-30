"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import numpy as np
import pytest

from iqpilot.selfdrive.test.longitudinal_maneuvers.plant import Plant

DURATION = 60.0
SETTLE_WITHIN = {True: 20.0, False: 25.0}
OVERSHOOT_TOLERANCE = 0.05
CRUISE_DECEL_LIMIT = 0.55


def drive(v0, cruise, personality):
  plant = Plant(lead_relevancy=False, speed=v0, distance_lead=200.0, personality=personality, model='blind')
  times, speeds, accels = [], [], []
  while plant.current_time < DURATION:
    log = plant.step(v_lead=40.0, prob_lead=0.0, v_cruise=cruise, pitch=0.0, prob_throttle=1.0)
    times.append(plant.current_time)
    speeds.append(log['speed'])
    accels.append(log['acceleration'])
  return np.array(times), np.array(speeds), np.array(accels)


@pytest.mark.parametrize('personality', [0, 1, 2])
@pytest.mark.parametrize('v0,cruise', [(20.0, 30.0), (5.0, 25.0), (20.0, 22.0), (30.0, 20.0), (30.0, 28.0)])
def test_converges_to_set_speed_without_overshoot(v0, cruise, personality):
  times, speeds, _ = drive(v0, cruise, personality)
  settled_by = SETTLE_WITHIN[cruise > v0]
  assert abs(speeds[np.searchsorted(times, settled_by)] - cruise) < 0.5
  assert abs(speeds[-1] - cruise) < OVERSHOOT_TOLERANCE
  assert speeds.max() - max(v0, cruise) < OVERSHOOT_TOLERANCE
  assert speeds.min() - min(v0, cruise) > -OVERSHOOT_TOLERANCE


@pytest.mark.parametrize('personality', [0, 1, 2])
def test_slowing_to_a_lower_set_speed_is_gentle(personality):
  _, _, accels = drive(30.0, 20.0, personality)
  assert -accels.min() < CRUISE_DECEL_LIMIT
  assert accels.max() < 0.05


@pytest.mark.parametrize('personality', [0, 1, 2])
def test_holding_the_set_speed_is_quiet(personality):
  _, speeds, accels = drive(25.0, 25.0, personality)
  assert np.abs(accels).max() < 0.05
  assert np.ptp(speeds) < OVERSHOOT_TOLERANCE
