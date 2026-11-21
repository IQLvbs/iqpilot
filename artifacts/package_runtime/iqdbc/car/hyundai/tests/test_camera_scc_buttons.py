"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""

import pytest

from iqdbc.car import gen_empty_fingerprint, structs
from iqdbc.car.hyundai.hyundaicanfd import CanBus
from iqdbc.car.hyundai.interface import CarInterface
from iqdbc.car.hyundai.values import CAR, HyundaiFlags

CRUISE_BUTTONS = 0x1CF
CRUISE_ALT_BUTTONS = 0x1AA


def camera_scc_car(candidate, alt_buttons):
  fingerprint = gen_empty_fingerprint()
  cp = CarInterface.get_params(candidate, fingerprint, [], True, False, False)
  cp.flags |= HyundaiFlags.CANFD_CAMERA_SCC.value
  cp.flags &= ~HyundaiFlags.CANFD_LKA_STEER_MSG.value
  if alt_buttons:
    cp.flags |= HyundaiFlags.CANFD_ALT_BUTTONS.value
  cp.openpilotLongitudinalControl = True
  cp_iq = CarInterface.get_params_iq(cp, candidate, fingerprint, [], True, False, False)
  car = CarInterface(cp, cp_iq)
  car.update([(10_000_000, [])])
  return car


@pytest.mark.parametrize("candidate", [CAR.KIA_EV6, CAR.HYUNDAI_TUCSON_4TH_GEN])
@pytest.mark.parametrize("alt_buttons", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_camera_scc_cars_under_longitudinal_never_copy_cruise_buttons_to_the_camera(candidate, alt_buttons, enabled):
  car = camera_scc_car(candidate, alt_buttons)
  camera_bus = CanBus(car.CP).CAM
  cc = structs.CarControl()
  cc.enabled = enabled
  cc.longActive = enabled
  cc.latActive = enabled
  cc = cc.as_reader()

  now = 10_000_000
  for _ in range(300):
    now += 10_000_000
    _, sends = car.apply(cc, structs.IQCarControl(), now)
    to_camera = [addr for addr, _, bus in sends if bus == camera_bus and addr in (CRUISE_BUTTONS, CRUISE_ALT_BUTTONS)]
    assert not to_camera
