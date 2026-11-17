"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from enum import IntFlag


class TeslaFlagsIQ(IntFlag):
  HAS_VEHICLE_BUS = 1  # 3-finger infotainment press signal is present on the VEHICLE bus with the deprecated Tesla harness installed
  COOP_STEERING = 2  # virtual torque blending
  FSD_VISUALIZATION = 4


class TeslaSafetyFlagsIQ:
  HAS_VEHICLE_BUS = 1
  FSD_VISUALIZATION = 2
