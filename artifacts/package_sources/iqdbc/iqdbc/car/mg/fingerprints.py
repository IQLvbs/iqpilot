"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from iqdbc.car.structs import CarParams
from iqdbc.car.mg.values import CAR

Ecu = CarParams.Ecu

FW_VERSIONS = {
  CAR.MG_5_EV: {
    (Ecu.eps, 0x721, None): [
      b'\x10gs\x16\x01',
    ],
    (Ecu.fwdCamera, 0x733, None): [
      b'\x10y\x00 \x01',
    ],
    (Ecu.fwdRadar, 0x734, None): [
      b'\x10y\x000\x01',
    ],
  },
}
