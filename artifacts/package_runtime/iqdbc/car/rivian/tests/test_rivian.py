import pytest

from iqdbc.can import CANPacker
from iqdbc.car import DT_CTRL, CanData, structs
from iqdbc.car.rivian.fingerprints import FW_VERSIONS
from iqdbc.car.rivian.interface import CarInterface
from iqdbc.car.rivian.values import CAR, FW_QUERY_CONFIG, WMI, ModelLine, ModelYear, RivianSafetyFlags


class TestRivian:
  def test_custom_fuzzy_fingerprinting(self, subtests):
    for platform in CAR:
      with subtests.test(platform=platform.name):
        for wmi in WMI:
          for line in ModelLine:
            for year in ModelYear:
              for bad in (True, False):
                vin = ["0"] * 17
                vin[:3] = wmi
                vin[3] = line.value
                vin[9] = year.value
                if bad:
                  vin[3] = "Z"
                vin = "".join(vin)

                matches = FW_QUERY_CONFIG.match_fw_to_car_fuzzy({}, vin, FW_VERSIONS)
                should_match = year in platform.config.years and not bad
                assert (matches == {platform}) == should_match, "Bad match"


def _rivian_interface(monkeypatch, tmp_path, gen2=False, alpha_long=False):
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
  fingerprint = {bus: {} for bus in range(7)}
  if not gen2:
    fingerprint[0][0x321] = 7
  cp = CarInterface.get_params(CAR.RIVIAN_R1_GEN1, fingerprint, [], alpha_long=alpha_long, is_release=False, docs=False)
  cp_iq = CarInterface.get_params_iq(cp, CAR.RIVIAN_R1_GEN1, fingerprint, [], alpha_long=alpha_long, is_release_iq=False, docs=False)
  interface = CarInterface(cp, cp_iq)
  interface.update([])
  return interface


def _adas_status_frames(counters):
  packer = CANPacker("rivian_primary_actuator")
  return [CanData(*packer.make_can_msg("VDM_AdasSts", 0, {"VDM_AdasStatus_Counter": c})) for c in counters]


class TestRivianAdasStatusForwarding:
  @pytest.mark.parametrize("gen2", [False, True])
  def test_forwards_every_received_frame_exactly_once(self, monkeypatch, tmp_path, gen2):
    interface = _rivian_interface(monkeypatch, tmp_path, gen2)
    cc = structs.CarControl()
    cc_iq = structs.IQCarControl()
    per_update = [[3, 4], [], [5], [], [], [6, 7, 8]]
    forwarded = []
    now = 0
    for counters in per_update:
      now += int(DT_CTRL * 1e9)
      interface.update([(now, _adas_status_frames(counters))])
      _, can_sends = interface.apply(cc.as_reader(), cc_iq, now)
      forwarded.append([msg[1][1] & 0xF for msg in can_sends if msg[0] == 0x162])
    assert forwarded == per_update

  @pytest.mark.parametrize("gen2", [False, True])
  def test_cancel_state_applies_to_every_forwarded_frame(self, monkeypatch, tmp_path, gen2):
    interface = _rivian_interface(monkeypatch, tmp_path, gen2)
    cc = structs.CarControl()
    cc.cruiseControl.cancel = True
    cc_iq = structs.IQCarControl()
    interface.update([(1, _adas_status_frames([1, 2]))])
    _, can_sends = interface.apply(cc.as_reader(), cc_iq, 1)
    sent = [msg for msg in can_sends if msg[0] == 0x162]
    assert [msg[1][1] & 0xF for msg in sent] == [1, 2]


class TestRivianAlphaLongitudinalGate:
  @staticmethod
  def _params(gen2, harness, alpha_long):
    fingerprint = {bus: {} for bus in range(7)}
    if not gen2:
      fingerprint[0][0x321] = 7
    if harness:
      fingerprint[5][0x31a] = 8
    cp = CarInterface.get_params(CAR.RIVIAN_R1_GEN1, fingerprint, [], alpha_long=alpha_long, is_release=False, docs=False)
    CarInterface.get_params_iq(cp, CAR.RIVIAN_R1_GEN1, fingerprint, [], alpha_long=alpha_long, is_release_iq=False, docs=False)
    return cp

  @pytest.mark.parametrize("gen2", (False, True), ids=("gen1", "gen2"))
  @pytest.mark.parametrize("harness", (False, True), ids=("no_harness", "harness"))
  @pytest.mark.parametrize("alpha_long", (False, True), ids=("toggle_off", "toggle_on"))
  def test_longitudinal_only_with_harness_and_toggle(self, gen2, harness, alpha_long):
    cp = self._params(gen2, harness, alpha_long)
    assert cp.alphaLongitudinalAvailable == harness
    assert cp.openpilotLongitudinalControl == (harness and alpha_long)
    assert bool(cp.safetyConfigs[0].safetyParam & RivianSafetyFlags.LONG_CONTROL.value) == (harness and alpha_long)
