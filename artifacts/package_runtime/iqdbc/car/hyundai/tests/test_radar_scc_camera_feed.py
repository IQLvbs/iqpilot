import pytest

from iqdbc.car import gen_empty_fingerprint, structs
from iqdbc.car.hyundai.hyundaicanfd import CanBus
from iqdbc.car.hyundai.interface import CarInterface
from iqdbc.car.hyundai.values import CAR, HyundaiFlags

RADAR_FLAGS = HyundaiFlags.CANFD | HyundaiFlags.CANFD_RADAR_SCC | HyundaiFlags.CANFD_ALT_GEARS
HDA2_EV = HyundaiFlags.CANFD | HyundaiFlags.CANFD_LKA_STEER_MSG | HyundaiFlags.EV


def make(monkeypatch, tmp_path, platform, flags, openpilot_long=True):
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
  fingerprint = gen_empty_fingerprint()
  cp = CarInterface.get_params(platform, fingerprint, [], openpilot_long, False, False)
  cp.flags = int(flags)
  cp.openpilotLongitudinalControl = openpilot_long
  cp_iq = CarInterface.get_params_iq(cp, platform, fingerprint, [], openpilot_long, False, False)
  return CarInterface(cp, cp_iq)


def sent_frames(interface, frames=100):
  cc = structs.CarControl().as_reader()
  cc_iq = structs.IQCarControl()
  out = []
  t = 0
  for _ in range(frames):
    t += 10_000_000
    interface.update([(t, [])])
    _, sends = interface.apply(cc, cc_iq, t)
    out.extend(sends)
  return out


def per_bus(sends, addr):
  return {bus: sum(1 for s in sends if s[0] == addr and s[2] == bus) for bus in {s[2] for s in sends if s[0] == addr}}


def test_radar_scc_car_feeds_the_camera_alongside_the_car(monkeypatch, tmp_path):
  interface = make(monkeypatch, tmp_path, CAR.GENESIS_GV70_1ST_GEN, RADAR_FLAGS)
  can = CanBus(interface.CP)
  sends = sent_frames(interface)

  assert per_bus(sends, 0x140) == {can.CAM: 100}
  assert per_bus(sends, 0x160) == {can.ECAN: 50, can.CAM: 50}
  assert per_bus(sends, 0x1A0) == {can.ECAN: 50, can.CAM: 50}
  ecan = [s for s in sends if s[0] == 0x1A0 and s[2] == can.ECAN]
  cam = [s for s in sends if s[0] == 0x1A0 and s[2] == can.CAM]
  assert [s[1] for s in ecan] == [s[1] for s in cam]


def test_hda2_longitudinal_car_feeds_the_camera_the_adas_status(monkeypatch, tmp_path):
  interface = make(monkeypatch, tmp_path, CAR.KIA_EV6, HDA2_EV)
  can = CanBus(interface.CP)

  assert per_bus(sent_frames(interface), 0x51) == {can.ACAN: 100, can.CAM: 100}


@pytest.mark.parametrize("platform,flags", [(CAR.GENESIS_GV70_1ST_GEN, RADAR_FLAGS), (CAR.KIA_EV6, HDA2_EV)])
def test_stock_longitudinal_cars_send_nothing_to_the_camera(monkeypatch, tmp_path, platform, flags):
  interface = make(monkeypatch, tmp_path, platform, flags, openpilot_long=False)
  can = CanBus(interface.CP)

  assert not [s for s in sent_frames(interface) if s[2] == can.CAM and s[0] in (0x140, 0x160, 0x1A0, 0x51)]


@pytest.mark.parametrize("platform,flags,streams", [
  (CAR.GENESIS_GV70_1ST_GEN, RADAR_FLAGS, [(0x160, 0), (0x160, 2)]),
  (CAR.KIA_EV6, HDA2_EV, [(0x51, 0), (0x51, 2), (0x160, 0), (0x160, 1)]),
])
def test_replacement_counters_advance_on_each_bus(monkeypatch, tmp_path, platform, flags, streams):
  sends = sent_frames(make(monkeypatch, tmp_path, platform, flags), frames=520)
  for address, bus in streams:
    counters = [data[2] for addr, data, src in sends if addr == address and src == bus]
    expected_frames = 520 if address == 0x51 else 260
    assert counters == [i % 256 for i in range(expected_frames)]
