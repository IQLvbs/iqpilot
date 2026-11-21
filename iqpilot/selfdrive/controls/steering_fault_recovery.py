"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from iqpilot.common.realtime import DT_CTRL

STEER_FAULT_RECOVERY_FRAMES = int(1.0 / DT_CTRL)


class SteeringFaultRecovery:
  def __init__(self) -> None:
    self.clear_frames = STEER_FAULT_RECOVERY_FRAMES

  def update(self, temporary: bool, permanent: bool) -> bool:
    if temporary or permanent:
      self.clear_frames = 0
    else:
      self.clear_frames = min(self.clear_frames + 1, STEER_FAULT_RECOVERY_FRAMES)
    return self.clear_frames == STEER_FAULT_RECOVERY_FRAMES
