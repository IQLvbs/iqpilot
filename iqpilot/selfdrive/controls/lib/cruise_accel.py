"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import numpy as np

from iqdbc.car.interfaces import ACCEL_MIN, ACCEL_MAX
from iqpilot.common.fastmath import clip as fast_clip

A_CRUISE_MIN = -0.5
A_CRUISE_MIN_NAV = -1.5
J_CRUISE = 1.0
CRUISE_STOP_SPEED = 1.0
MIN_ALLOW_THROTTLE_SPEED = 2.5


def get_coast_accel(pitch):
  return np.sin(pitch) * -5.65 - 0.3


def get_carcontrol_coast_accel(car_control):
  if len(car_control.orientationNED) == 3:
    return get_coast_accel(car_control.orientationNED[1])
  return ACCEL_MAX


def get_cruise_accel(max_accel, v_cruise, v_ego, a_cruise_prev, dt, accel_coast, allow_throttle, min_accel=A_CRUISE_MIN):
  if not allow_throttle:
    clipped_accel_coast = max(accel_coast, ACCEL_MIN)
    coast_limit = np.interp(v_ego, [MIN_ALLOW_THROTTLE_SPEED, MIN_ALLOW_THROTTLE_SPEED * 2], [max_accel, clipped_accel_coast])
    max_accel = min(max_accel, coast_limit)

  target_accel = fast_clip(v_cruise - v_ego, min_accel, max_accel)
  target_accel = float(fast_clip(target_accel, a_cruise_prev - J_CRUISE * dt, a_cruise_prev + J_CRUISE * dt))

  cruise_should_stop = v_cruise == 0.0 and v_ego < CRUISE_STOP_SPEED
  return target_accel, cruise_should_stop
