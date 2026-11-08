"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import math
import numpy as np

from iqdbc.can.packer import CANPacker
from iqdbc.car import Bus, structs
from iqdbc.car.lateral import apply_std_steer_angle_limits, apply_steer_angle_limits_vm
from iqdbc.car.interfaces import CarControllerBase
from iqdbc.car.byd import bydcan
from iqdbc.car.byd.carstate import EPS_STATE_LATCHED_FAULT
from iqdbc.car.byd.values import CarControllerParams as CCP
from iqdbc.car.vehicle_model import VehicleModel

LongCtrlState = structs.CarControl.Actuators.LongControlState

ACC_STEP = 3
ACC_DT = ACC_STEP * 0.01


class CarController(CarControllerBase):
  def __init__(self, dbc_names, CP, CP_IQ):
    super().__init__(dbc_names, CP, CP_IQ)
    self.packer = CANPacker(dbc_names[Bus.pt])
    self.apply_angle_last = 0.0
    self.accel_last = 0.0
    self.VM = VehicleModel(CP)
    self.angle_cmd_filtered = 0.0
    self.angle_handoff = False

  def update(self, CC, CC_IQ, CS, now_nanos):
    can_sends = []
    actuators = CC.actuators

    # 0x1E2 and 0x316 stream continuously: the EPS latches a fault if the stream stops while it is actuating.
    if self.frame % CCP.STEER_STEP == 0:
      measured = CS.out.steeringAngleDeg

      if abs(measured) > CCP.MAX_STEER_ANGLE:
        self.angle_handoff = True
      elif abs(measured) < CCP.MAX_STEER_ANGLE_RESUME:
        self.angle_handoff = False

      faulting = CS.eps_state == EPS_STATE_LATCHED_FAULT
      steer_req = bool(CC.latActive) and not faulting and not self.angle_handoff

      if steer_req:
        alpha = math.exp(-2.0 * math.pi * CCP.STEER_LOWPASS_HZ * CCP.STEER_DT)
        self.angle_cmd_filtered = alpha * self.angle_cmd_filtered + (1.0 - alpha) * actuators.steeringAngleDeg
      else:
        self.angle_cmd_filtered = measured

      apply_angle = apply_std_steer_angle_limits(self.angle_cmd_filtered, self.apply_angle_last, CS.out.vEgoRaw,
                                                 measured, steer_req, CCP.ANGLE_LIMITS)
      if steer_req:
        apply_angle = float(np.clip(apply_angle, measured - CCP.MAX_ANGLE_ERROR, measured + CCP.MAX_ANGLE_ERROR))
        apply_angle = apply_steer_angle_limits_vm(apply_angle, self.apply_angle_last, CS.out.vEgoRaw,
                                                  measured, steer_req, CCP, self.VM)
      self.apply_angle_last = apply_angle

      lkas_state = bydcan.LKAS_STATE_ACTIVE if steer_req else bydcan.LKAS_STATE_IDLE
      can_sends.append(bydcan.create_steering_control(self.packer, apply_angle, steer_req))
      can_sends.append(bydcan.create_lkas_hud(self.packer, lkas_state, steer_req, CS.lkas_hud, CC.hudControl))

    accel = 0.0
    if self.CP.openpilotLongitudinalControl and self.frame % ACC_STEP == 0:
      if CC.longActive:
        accel = self._apply_long_limits(actuators, CS, CC)
      else:
        self.accel_last = float(np.clip(CS.out.aEgo, CCP.ACCEL_MIN, CCP.ACCEL_MAX))

      lcs = actuators.longControlState
      stopping = (lcs == LongCtrlState.stopping) or (CS.out.standstill and accel <= 0.0)
      resume = (lcs == LongCtrlState.starting) or CC.cruiseControl.resume
      can_sends.append(bydcan.create_acc_cmd(self.packer, accel, CC.longActive, CS.acc_cmd,
                                             standstill=stopping and CS.out.standstill, resume=resume))

    new_actuators = actuators.as_builder()
    new_actuators.steeringAngleDeg = float(self.apply_angle_last)
    new_actuators.accel = accel

    self.frame += 1
    return new_actuators, can_sends

  def _apply_long_limits(self, actuators, CS, CC) -> float:
    target = float(np.clip(actuators.accel, CCP.ACCEL_MIN, CCP.ACCEL_MAX))

    launch = CS.out.vEgo < 2.0 and target > 0.0
    up = (CCP.JERK_UP_LAUNCH if launch else CCP.JERK_UP) * ACC_DT
    down = CCP.JERK_DOWN * ACC_DT

    resume = (actuators.longControlState == LongCtrlState.starting) or CC.cruiseControl.resume
    if resume and CS.out.standstill and self.accel_last < 0.0:
      self.accel_last = 0.0

    accel = float(np.clip(target, self.accel_last - down, self.accel_last + up))
    self.accel_last = accel
    return accel
