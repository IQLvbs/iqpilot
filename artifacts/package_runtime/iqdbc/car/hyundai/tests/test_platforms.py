"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""

import pytest

from iqdbc.car import gen_empty_fingerprint, structs
from iqdbc.car.hyundai.interface import CarInterface
from iqdbc.car.hyundai.values import CAR


@pytest.mark.parametrize("candidate", list(CAR), ids=lambda candidate: candidate.value)
@pytest.mark.parametrize("alpha_long", (False, True), ids=("stock_long", "openpilot_long"))
def test_every_platform_builds_its_interface_and_runs_the_controller(candidate, alpha_long):
  fingerprint = gen_empty_fingerprint()
  cp = CarInterface.get_params(candidate, fingerprint, [], alpha_long, False, False)
  cp_iq = CarInterface.get_params_iq(cp, candidate, fingerprint, [], alpha_long, False, False)
  car = CarInterface(cp, cp_iq)
  car.update([])

  cc = structs.CarControl()
  cc.enabled = True
  cc.latActive = True
  cc.longActive = cp.openpilotLongitudinalControl
  cc.actuators.torque = 0.1
  cc = cc.as_reader()
  now = 0
  for _ in range(250):
    now += 10_000_000
    _, sends = car.apply(cc, structs.IQCarControl(), now)
    assert isinstance(sends, list)
