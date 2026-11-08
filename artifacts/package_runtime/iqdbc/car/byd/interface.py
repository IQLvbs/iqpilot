"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from iqdbc.car import get_safety_config, structs
from iqdbc.car.interfaces import CarInterfaceBase
from iqdbc.car.byd.carcontroller import CarController
from iqdbc.car.byd.carstate import CarState
from iqdbc.car.byd.values import BydFlags, BydSafetyFlags


class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "byd"

    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.byd)]

    ret.steerControlType = structs.CarParams.SteerControlType.angle
    # Delay and rate limits are a set: near-zero delay needs the fast rate curve and the 2 Hz command low-pass.
    ret.steerActuatorDelay = 0.01
    ret.steerLimitTimer = 0.4

    ret.radarUnavailable = True

    # Fingerprinting runs with the relay closed, so the harness type cannot be inferred; gateway is explicit opt-in.
    gateway_harness = bool(ret.flags & BydFlags.GATEWAY_HARNESS)

    ret.alphaLongitudinalAvailable = gateway_harness
    if alpha_long and gateway_harness:
      ret.openpilotLongitudinalControl = True
      ret.safetyConfigs[0].safetyParam |= BydSafetyFlags.LONG_CONTROL.value

      ret.longitudinalActuatorDelay = 0.5
      ret.vEgoStarting = 0.3
      ret.stopAccel = -0.5
      ret.startAccel = 1.5
      ret.startingState = True

      ret.longitudinalTuning.kpBP = [0.0, 5.0, 35.0]
      ret.longitudinalTuning.kpV = [0.5, 0.4, 0.3]
      ret.longitudinalTuning.kiBP = [0.0, 35.0]
      ret.longitudinalTuning.kiV = [0.03, 0.02]

    return ret

  @staticmethod
  def _get_params_iq(stock_cp: structs.CarParams, ret: structs.IQCarParams, candidate, fingerprint,
                     car_fw, alpha_long: bool, is_release_iq: bool, docs: bool) -> structs.IQCarParams:
    if stock_cp.openpilotLongitudinalControl:
      ret.longitudinalStoppingSpeedOverride = 0.3

    return ret
