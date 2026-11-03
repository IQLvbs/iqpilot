"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from iqdbc.car import get_safety_config, structs
from iqdbc.car.interfaces import CarInterfaceBase
from iqdbc.car.mg.carcontroller import CarController
from iqdbc.car.mg.carstate import CarState


class CarInterface(CarInterfaceBase):
  CarState = CarState
  CarController = CarController

  @staticmethod
  def _get_params(ret: structs.CarParams, candidate, fingerprint, car_fw, alpha_long, is_release, docs) -> structs.CarParams:
    ret.brand = "mg"

    ret.safetyConfigs = [get_safety_config(structs.CarParams.SafetyModel.mg)]

    ret.steerActuatorDelay = 0.3
    CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)

    ret.steerControlType = structs.CarParams.SteerControlType.torque
    ret.radarUnavailable = True
    ret.alphaLongitudinalAvailable = False

    return ret
