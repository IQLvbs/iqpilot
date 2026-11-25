import pytest

from iqdbc.can import CANPacker
from iqdbc.car import Bus, gen_empty_fingerprint, structs
from iqdbc.car.hyundai.interface import CarInterface
from iqdbc.car.hyundai.values import CAR, DBC, HyundaiFlags, HyundaiFlagsIQ, HyundaiSafetyFlags


@pytest.mark.parametrize("candidate", [CAR.HYUNDAI_KONA_2022, CAR.HYUNDAI_KONA_EV_2022])
@pytest.mark.parametrize("offset,extra_panda", [(0, False), (0, True), (4, True)])
@pytest.mark.parametrize("alpha_long", [False, True])
def test_camera_cruise_uses_harness_panda(candidate, offset, extra_panda, alpha_long):
  fp = gen_empty_fingerprint()
  if extra_panda:
    fp[4][0x123] = 8
  fp[offset][0x391] = 8
  fp[offset + 2][0x421] = 8
  cp = CarInterface.get_params(candidate, fp, [], alpha_long, False, False)
  iq = CarInterface.get_params_iq(cp, candidate, fp, [], alpha_long, False, False)
  assert cp.flags & HyundaiFlags.HAS_LDA_BUTTON
  assert iq.flags & HyundaiFlagsIQ.HAS_LFA_BUTTON
  assert len(cp.safetyConfigs) == 1 + offset // 4
  if offset:
    assert cp.safetyConfigs[0].safetyModel == structs.CarParams.SafetyModel.noOutput
    assert cp.safetyConfigs[0].safetyParam == 0
  active = cp.safetyConfigs[-1]
  assert active.safetyModel == structs.CarParams.SafetyModel.hyundai
  assert active.safetyParam & HyundaiSafetyFlags.CAMERA_SCC

  car = CarInterface(cp, iq)
  car.update([(0, [])])
  packer = CANPacker(DBC[candidate][Bus.pt])
  scc = packer.make_can_msg("SCC12", offset + 2, {"ACCMode": 1})
  state, _ = car.update([(10_000_000, [scc])])
  if not alpha_long:
    assert state.cruiseState.enabled

  cc = structs.CarControl()
  cc.cruiseControl.cancel = True
  sends = []
  for frame in range(12):
    _, messages = car.apply(cc.as_reader(), structs.IQCarControl(), (frame + 1) * 10_000_000)
    sends.extend(messages)
  assert {bus for addr, _, bus in sends if addr == 0x340} == {offset}
  if alpha_long:
    assert {bus for _, _, bus in sends} == {offset}
    assert any(addr == 0x421 for addr, _, _ in sends)
  else:
    assert {bus for addr, _, bus in sends if addr == 0x4F1} == {offset + 2}
