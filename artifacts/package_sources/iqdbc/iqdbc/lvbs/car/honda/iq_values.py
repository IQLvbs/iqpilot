"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""

from enum import IntFlag


class HondaFlagsIQ(IntFlag):
  NIDEC_HYBRID = 1
  EPS_MODIFIED = 2
  HYBRID_ALT_BRAKEHOLD = 4
  HAS_CAMERA_MESSAGES = 8


class HondaSafetyFlagsIQ:
  NIDEC_HYBRID = 1
  GAS_INTERCEPTOR = 2
