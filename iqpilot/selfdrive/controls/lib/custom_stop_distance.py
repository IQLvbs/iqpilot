"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import numpy as np

from iqdbc.car.interfaces import ACCEL_MIN
from iqpilot.common.params import Params
from iqpilot.common.realtime import DT_MDL
from iqpilot.selfdrive.iqmodeld.config import ModelConstants

CUSTOM_STOP_DISTANCE_PARAM = "IQCustomStopDistance"
MIN_DISTANCE_M = -2
MAX_DISTANCE_M = 2

STOPPED_DISTANCE_FADE_BP = [0., 3.]
MIN_ADJUSTED_D_REL = 1.0

E2E_STOP_PLAN_VEL_THRESHOLD = 1.0
E2E_STOP_MIN_BRAKING = -0.1
E2E_STOP_MIN_DIST = 2.0
E2E_STOP_HOLD_MAX_V = 0.5
E2E_STOP_HOLD_BUFFER = 2.0

def get_sanitize_int_param(key, min_val, max_val, params):
  stored = params.get(key, return_default=True)
  bounded = min(max(stored, min_val), max_val)
  if bounded != stored:
    params.put(key, bounded)
  return bounded


class CustomStopDistance:
  def __init__(self):
    self.params = Params()
    self.frame = 0
    self.distance = 0.
    self.read_params()

  def read_params(self) -> None:
    self.distance = float(get_sanitize_int_param(CUSTOM_STOP_DISTANCE_PARAM, MIN_DISTANCE_M, MAX_DISTANCE_M, self.params))

  def update(self) -> None:
    if self.frame % int(3 / DT_MDL) == 0:
      self.read_params()
    self.frame += 1

  def apply_lead(self, lead_dict: dict) -> dict:
    if self.distance == 0. or not lead_dict.get('status', False):
      return lead_dict

    offset = self.distance * float(np.interp(lead_dict['vLead'], STOPPED_DISTANCE_FADE_BP, [1., 0.]))
    adjusted = lead_dict['dRel'] - offset
    if self.distance > 0:
      lead_dict['dRel'] = min(lead_dict['dRel'], max(adjusted, MIN_ADJUSTED_D_REL))
    else:
      lead_dict['dRel'] = max(lead_dict['dRel'], adjusted)
    return lead_dict

  def adjust_e2e_stop(self, a_target: float, should_stop: bool, v_ego: float, model_msg) -> tuple[float, bool]:
    if self.distance <= 0.:
      return a_target, should_stop

    x = model_msg.position.x
    v = model_msg.velocity.x
    if len(x) != ModelConstants.IDX_N or len(v) != ModelConstants.IDX_N:
      return a_target, should_stop

    if float(v[-1]) > E2E_STOP_PLAN_VEL_THRESHOLD:
      return a_target, should_stop

    stop_distance = float(x[-1])

    if v_ego < E2E_STOP_HOLD_MAX_V:
      if stop_distance <= self.distance + E2E_STOP_HOLD_BUFFER:
        should_stop = True
    elif a_target < E2E_STOP_MIN_BRAKING:
      adjusted_distance = max(stop_distance - self.distance, E2E_STOP_MIN_DIST)
      a_required = max(-(v_ego ** 2) / (2 * adjusted_distance), ACCEL_MIN)
      if a_required < a_target:
        a_target = float(a_required)

    return a_target, should_stop
