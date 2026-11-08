"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from iqdbc.car.structs import CarParams
from iqdbc.car.byd.values import CAR

Ecu = CarParams.Ecu

# An empty ECU dict would match every car on the road, so the placeholder is a version no car reports.
FW_VERSIONS = {
  CAR.BYD_SEALION_7: {
    (Ecu.engine, 0x7e0, None): [
      b'PLACEHOLDER_UNTIL_CAPTURED',
    ],
  },
}
