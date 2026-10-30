"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from dataclasses import dataclass, field
from collections.abc import Callable

import numpy as np

from iqpilot.selfdrive.test.longitudinal_maneuvers.plant import Plant

COLLISION_GAP = 0.4
MAX_BRAKE = 3.5
COMFORT_AVOIDANCE_BRAKE = 2.0
REACTION_TIME = 0.6


@dataclass
class Scenario:
  speed: float
  gap: float
  lead_speed: Callable[[float], float]
  duration: float = 30.0
  model: str = 'follow'
  personality: int = 1
  lead_visible: Callable[[float], float] = lambda t: 1.0
  cruise: float = 50.0
  extra: dict = field(default_factory=dict)


@dataclass
class Outcome:
  min_gap: float
  max_decel: float
  max_accel: float
  jerk_p99: float
  fcw_frames: int
  assist_frames: int
  frames: int
  final_speed: float
  final_gap: float
  started: bool
  min_time_gap: float


def _min_time_gap(gaps, speeds) -> float:
  gaps, speeds = np.array(gaps), np.array(speeds)
  moving = speeds > 3.0
  return float(np.min(gaps[moving] / speeds[moving])) if moving.any() else float('inf')


def run(scenario: Scenario) -> Outcome:
  plant = Plant(lead_relevancy=True, speed=scenario.speed, distance_lead=scenario.gap,
                personality=scenario.personality, model=scenario.model)
  gaps, accels, fcw, assist, speeds = [], [], 0, 0, []
  started = False
  while plant.current_time < scenario.duration:
    t = plant.current_time
    v_lead = scenario.lead_speed(t)
    log = plant.step(v_lead, scenario.lead_visible(t), scenario.cruise, 0.0, 1.0)
    gaps.append(log['distance_lead'] - log['distance'])
    accels.append(log['acceleration'])
    speeds.append(log['speed'])
    fcw += bool(log['fcw'])
    assist += bool(getattr(getattr(plant.planner, 'assist', None), 'active', False))
    started = started or (scenario.speed < 0.1 and log['speed'] > 0.5)
  accels = np.array(accels)
  jerk = np.diff(accels) / plant.ts
  return Outcome(
    min_gap=float(np.min(gaps)), max_decel=float(-accels.min()), max_accel=float(accels.max()),
    jerk_p99=float(np.percentile(np.abs(jerk), 99)), fcw_frames=fcw, assist_frames=assist, frames=len(accels),
    final_speed=float(log['speed']), final_gap=float(gaps[-1]), started=started,
    min_time_gap=_min_time_gap(gaps, speeds),
  )


def stopping_distance(speed: float, decel: float = MAX_BRAKE) -> float:
  return speed ** 2 / (2.0 * decel)


def avoidable(speed: float, gap: float, lead_speed: float, lead_decel: float | None = None,
              brake: float = COMFORT_AVOIDANCE_BRAKE, reaction: float = REACTION_TIME) -> bool:
  lead_travel = 0.0 if lead_decel is None else lead_speed ** 2 / (2.0 * lead_decel)
  reaction_travel = (speed - lead_speed) * reaction if lead_decel is None else speed * reaction
  if lead_decel is None:
    return stopping_distance(speed, brake) - stopping_distance(lead_speed, brake) + reaction_travel <= gap - COLLISION_GAP - 1.0
  return stopping_distance(speed, brake) + reaction_travel <= gap + lead_travel - COLLISION_GAP - 1.0
