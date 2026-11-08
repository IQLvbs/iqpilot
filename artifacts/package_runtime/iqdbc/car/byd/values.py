"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from dataclasses import dataclass, field
from enum import IntFlag, StrEnum

from iqdbc.car import Bus, CarSpecs, DbcDict, PlatformConfig, Platforms, structs
from iqdbc.car.lateral import AngleSteeringLimits, MAX_LATERAL_ACCEL, MAX_LATERAL_JERK
from iqdbc.car.docs_definitions import CarDocs, CarHarness, CarParts
from iqdbc.car.fw_query_definitions import FwQueryConfig, Request, StdQueries
from iqdbc.car.vin import Vin

Ecu = structs.CarParams.Ecu


class CarControllerParams:
  STEER_STEP = 2
  STEER_DT = 0.02

  ANGLE_LIMITS: AngleSteeringLimits = AngleSteeringLimits(
    85.,
    ([0., 2., 5., 8., 15.], [0.3, 1.0, 1.5, 3.7, 3.0]),
    ([0., 2., 5., 8., 15.], [0.5, 1.2, 1.5, 5.4, 4.0]),
    MAX_LATERAL_ACCEL=MAX_LATERAL_ACCEL,
    MAX_LATERAL_JERK=MAX_LATERAL_JERK,
    MAX_ANGLE_RATE=10.,
  )

  STEER_LOWPASS_HZ = 2.0
  MAX_ANGLE_ERROR = 10.0

  # The EPS latches a fault past ~90 deg and only an ignition cycle clears it.
  MAX_STEER_ANGLE = 80.0
  MAX_STEER_ANGLE_RESUME = 65.0

  STEER_DRIVER_OVERRIDE = 80

  ACCEL_MIN = -3.0
  ACCEL_MAX = 1.5

  JERK_UP = 2.5
  JERK_UP_LAUNCH = 4.0
  JERK_DOWN = 5.0


class BydSafetyFlags(IntFlag):
  LONG_CONTROL = 1


class BydFlags(IntFlag):
  GATEWAY_HARNESS = 1


class WMI(StrEnum):
  BYD_AUTO = "LGX"


class ModelYear(StrEnum):
  R_2024 = "R"
  S_2025 = "S"
  T_2026 = "T"


@dataclass
class BydCarDocs(CarDocs):
  package: str = "All"
  car_parts: CarParts = field(default_factory=CarParts.common([CarHarness.custom]))


@dataclass
class BydPlatformConfig(PlatformConfig):
  dbc_dict: DbcDict = field(default_factory=lambda: {Bus.pt: 'byd_sealion_7'})
  wmis: set[WMI] = field(default_factory=set)
  years: set[ModelYear] = field(default_factory=set)
  vds_prefixes: set[str] = field(default_factory=set)


class CAR(Platforms):
  BYD_SEALION_7 = BydPlatformConfig(
    [BydCarDocs("BYD Sealion 7 2024-25")],
    CarSpecs(mass=2090., wheelbase=2.93, steerRatio=16.0, centerToFrontRatio=0.44),
    wmis={WMI.BYD_AUTO},
    years={ModelYear.R_2024, ModelYear.S_2025, ModelYear.T_2026},
  )


def match_fw_to_car_fuzzy(live_fw_versions, vin, offline_fw_versions) -> set[str]:
  vin_obj = Vin(vin)
  year = vin_obj.vis[:1]

  candidates = set()
  for platform in CAR:
    cfg = platform.config
    if not cfg.vds_prefixes or vin_obj.wmi not in cfg.wmis or year not in cfg.years:
      continue
    if any(vin_obj.vds.startswith(p) for p in cfg.vds_prefixes):
      candidates.add(platform)

  return {str(c) for c in candidates}


FW_QUERY_CONFIG = FwQueryConfig(
  # BYD ECUs NRC 0xF188 but answer 0xF195.
  requests=[
    Request(
      [StdQueries.SUPPLIER_SOFTWARE_VERSION_REQUEST],
      [StdQueries.SUPPLIER_SOFTWARE_VERSION_RESPONSE],
      bus=0,
    ),
  ],
  non_essential_ecus={Ecu.fwdCamera: list(CAR)},
  match_fw_to_car_fuzzy=match_fw_to_car_fuzzy,
)


DBC = CAR.create_dbc_map()
