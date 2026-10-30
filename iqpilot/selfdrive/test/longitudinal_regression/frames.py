"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from dataclasses import dataclass, asdict


@dataclass
class Frame:
  t: float
  v_ego: float
  a_ego: float
  v_cruise: float
  enabled: bool
  long_active: bool
  personality: int
  gas_pressed: bool
  brake_pressed: bool
  standstill: bool
  lead_status: bool
  lead_d: float
  lead_v: float
  lead_a: float
  lead_prob: float
  model_a: float
  model_stop: bool
  recorded_a: float
  recorded_stop: bool
  recorded_source: int
  recorded_fcw: bool
  a_target: float
  should_stop: bool
  fcw: bool
  source: int

  def to_dict(self):
    return asdict(self)
