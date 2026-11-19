"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from dataclasses import dataclass, field

from iqdbc.car import Bus, CarSpecs, DbcDict, PlatformConfig, Platforms
from iqdbc.car.docs_definitions import CarHarness, CarDocs, CarParts
from iqdbc.car.fw_query_definitions import FwQueryConfig, Request, StdQueries


@dataclass
class MgCarDocs(CarDocs):
  package: str = "All"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.vw_a]))


@dataclass
class MgPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.pt: 'mg'})


class CAR(Platforms):
  MG_5_EV = MgPlatformConfig([MgCarDocs("MG 5 EV 2021")], CarSpecs(mass=1640., wheelbase=2.66, steerRatio=15.8))


FW_QUERY_CONFIG = FwQueryConfig(
  requests=[
    Request(
      [StdQueries.TESTER_PRESENT_REQUEST, StdQueries.MANUFACTURER_ECU_HARDWARE_NUMBER_REQUEST],
      [StdQueries.TESTER_PRESENT_RESPONSE, StdQueries.MANUFACTURER_ECU_HARDWARE_NUMBER_RESPONSE],
      bus=1,
    ),
  ],
)


class CarControllerParams:
  STEER_STEP = 2
  STEER_MAX = 300
  STEER_DELTA_UP = 6
  STEER_DELTA_DOWN = 10
  STEER_DRIVER_ALLOWANCE = 100
  STEER_DRIVER_MULTIPLIER = 2
  STEER_DRIVER_FACTOR = 100

  def __init__(self, CP):
    pass


DBC = CAR.create_dbc_map()
