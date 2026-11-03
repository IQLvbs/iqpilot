"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import pytest

from iqdbc.car import gen_empty_fingerprint, structs
from iqdbc.car.subaru.interface import CarInterface
from iqdbc.car.subaru.values import CAR
from iqdbc.safety.tests.libsafety import libsafety_py


@pytest.mark.parametrize("candidate", list(CAR), ids=lambda candidate: candidate.value)
@pytest.mark.parametrize("alpha_long", (False, True), ids=("stock_long", "openpilot_long"))
def test_controller_frames_match_configured_safety(candidate, alpha_long, monkeypatch, tmp_path):
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path / candidate.value))
  fingerprint = gen_empty_fingerprint()
  cp = CarInterface.get_params(candidate, fingerprint, [], alpha_long, False, False)
  cp_iq = CarInterface.get_params_iq(cp, candidate, fingerprint, [], alpha_long, False, False)
  interface = CarInterface(cp, cp_iq)
  interface.update([])

  safety_config = cp.safetyConfigs[-1]
  safety = libsafety_py.libsafety
  assert safety.set_safety_hooks(safety_config.safetyModel.raw, safety_config.safetyParam) == 0
  safety.init_tests()
  safety.set_controls_allowed(True)

  control = structs.CarControl.new_message()
  control.enabled = True
  control.latActive = True
  control.longActive = cp.openpilotLongitudinalControl
  control.actuators.torque = 0.01
  control.actuators.accel = 0.0

  sent = 0
  for frame in range(60):
    _, can_sends = interface.apply(control.as_reader(), structs.IQCarControl())
    for address, data, bus in can_sends:
      sent += 1
      packet = libsafety_py.make_CANPacket(address, bus, data)
      rejection = f"{candidate.value} frame {frame}: safety rejected address={address:#x} bus={bus} data={data.hex()}"
      assert safety.safety_tx_hook(packet), rejection
  assert sent > 0
