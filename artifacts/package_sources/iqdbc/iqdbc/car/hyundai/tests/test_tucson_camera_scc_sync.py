"""Real parser/controller and native safety regressions. No vehicle access."""
import pytest

from iqdbc.can import CANPacker, CANParser
from iqdbc.car import Bus, gen_empty_fingerprint, structs
from iqdbc.car.hyundai.interface import CarInterface
from iqdbc.car.hyundai.values import CAR, DBC, HyundaiFlags
from iqdbc.safety.tests.libsafety import libsafety_py
from iqpilot.common.params import Params

FLAGS = HyundaiFlags.CANFD | HyundaiFlags.CANFD_CAMERA_SCC | HyundaiFlags.CANFD_ALT_BUTTONS | HyundaiFlags.CANFD_ALT_GEARS
DT = 10_000_000
REPLACEMENTS = {(0x12A, 0), (0xEA, 2), (0x175, 2), (0x1A0, 0), (0x1E0, 0)}


class Car:
  def __init__(self, candidate=CAR.HYUNDAI_TUCSON_4TH_GEN, flags=FLAGS, longitudinal=True, multi_panda=False):
    fp = gen_empty_fingerprint()
    cp = CarInterface.get_params(candidate, fp, [], True, False, False)
    cp.flags = int(flags)
    cp.openpilotLongitudinalControl = longitudinal
    if multi_panda:
      cp.safetyConfigs = list(cp.safetyConfigs) * 2
    iq = CarInterface.get_params_iq(cp, candidate, fp, [], True, False, False)
    self.ci = CarInterface(cp, iq)
    self.packer = CANPacker(DBC[candidate][Bus.pt])
    self.now = 0
    self.popup = self.mode = self.fault = 0

  def tick(self, *, omitted=(), corrupt=(), extra=()):
    self.now += DT
    frames = []
    inputs = [
      ("CRUISE_BUTTONS_ALT", 0, {}), ("TCS", 0, {"DriverBraking": 0}),
      ("WHEEL_SPEEDS", 0, {}), ("MDPS", 0, {"STEERING_COL_TORQUE": 0, "LKA_FAULT": self.fault}),
      ("LFA", 2, {"LKA_MODE": self.mode}), ("SCC_CONTROL", 2, {}),
      ("LFAHDA_CLUSTER", 2, {"HDA_InfoPUDis": self.popup}),
    ]
    for name, bus, values in inputs:
      if name in omitted:
        continue
      addr, data, _ = self.packer.make_can_msg(name, bus, values)
      if name in corrupt:
        data = bytearray(data)
        data[0] ^= 1
      frames.append((addr, bytes(data), bus))
    ret, _ = self.ci.update([(self.now, frames + list(extra))])
    return ret

  def apply(self, active=False):
    cc = structs.CarControl.new_message()
    cc.enabled = cc.latActive = active
    cc.actuators.torque = 0.15 if active else 0.0
    _, messages = self.ci.apply(cc.as_reader(), structs.IQCarControl(), self.now)
    return messages

  def lfa(self):
    return next((address, data, bus) for address, data, bus in self.apply(True) if (address, bus) == (0x12A, 0))

  def ready(self):
    Params().put_bool("ControlsReady", True)
    for _ in range(205):
      self.tick()


@pytest.fixture(autouse=True)
def isolated_params(monkeypatch, tmp_path):
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
  Params().put_bool("ControlsReady", False)


def torque(frame):
  data = frame[1]
  return (((data[6] & 15) << 7) | (data[5] >> 1)) - 1024


def native(frame):
  address, data, bus = frame
  return libsafety_py.make_CANPacket(address, bus, data)


def test_replacements_exist_at_safety_handoff_instead_of_one_second_later():
  car = Car()
  car.tick()
  Params().put_bool("ControlsReady", True)
  car.tick()
  # Collect one normal 20Hz cluster period, still before the earliest native
  # relay handoff in the saved startup traces. No engagement is required.
  sent = set()
  for _ in range(5):
    sent.update((a, b) for a, _, b in car.apply())
    car.tick()
  assert REPLACEMENTS <= sent


@pytest.mark.parametrize("name,attr", [("LFA", "lfa"), ("MDPS", "mdps"), ("TCS", "tcs"),
                                      ("SCC_CONTROL", "scc_control"), ("LFAHDA_CLUSTER", "lfahda_cluster")])
def test_missing_frames_never_become_default_zero_cache_and_late_valid_frame_recovers(name, attr):
  car = Car()
  Params().put_bool("ControlsReady", True)
  for _ in range(205):
    car.tick(omitted={name})
  assert getattr(car.ci.CS, attr) is None
  car.tick()
  assert getattr(car.ci.CS, attr) is not None


@pytest.mark.parametrize("name,attr", [("LFA", "lfa"), ("MDPS", "mdps"), ("TCS", "tcs"),
                                      ("SCC_CONTROL", "scc_control"), ("LFAHDA_CLUSTER", "lfahda_cluster")])
def test_initial_bad_crc_is_not_a_valid_replacement(name, attr):
  car = Car()
  car.tick(corrupt={name})
  assert getattr(car.ci.CS, attr) is None
  car.tick()
  assert getattr(car.ci.CS, attr) is not None


def test_cached_dictionary_follows_new_parsed_camera_values():
  car = Car()
  car.tick()
  cached = car.ci.CS.lfahda_cluster
  assert cached is not None
  car.popup = 5
  car.tick()
  assert cached["HDA_InfoPUDis"] == 5


@pytest.mark.parametrize("candidate,flags,longitudinal", [
  (CAR.KIA_EV6, FLAGS, True), (CAR.HYUNDAI_TUCSON_4TH_GEN, FLAGS, False),
  (CAR.HYUNDAI_TUCSON_4TH_GEN, FLAGS | HyundaiFlags.CANFD_HDA2, True),
  (CAR.HYUNDAI_TUCSON_4TH_GEN, FLAGS | HyundaiFlags.ANGLE_CONTROL, True),
])
def test_other_profiles_keep_original_camera_registration(candidate, flags, longitudinal):
  car = Car(candidate, flags, longitudinal)
  assert 0x12A not in car.ci.can_parsers[Bus.cam].addresses
  assert 0x1E0 not in car.ci.can_parsers[Bus.cam].addresses


def test_offset_bus_profile_keeps_original_camera_registration():
  car = Car(multi_panda=True)
  assert car.ci.can_parsers[Bus.pt].bus == 4
  assert 0x12A not in car.ci.can_parsers[Bus.cam].addresses
  assert 0x1E0 not in car.ci.can_parsers[Bus.cam].addresses


def test_real_mdps_fault_and_check_lfa_popup_are_still_visible():
  car = Car()
  car.popup, car.mode, car.fault = 3, 7, 1
  car.ready()
  ret = car.tick()
  assert ret.steerFaultTemporary
  output = CANParser(DBC[CAR.HYUNDAI_TUCSON_4TH_GEN][Bus.pt], [("LFAHDA_CLUSTER", 20)], 0)
  for _ in range(6):
    output.update([(car.now, car.apply())])
    car.tick()
  assert output.vl["LFAHDA_CLUSTER"]["HDA_InfoPUDis"] == 3


def test_torque_safety_rejection_recovers_from_native_zero_reference():
  car = Car()
  car.ready()
  safety = libsafety_py.libsafety
  assert safety.set_safety_hooks(structs.CarParams.SafetyModel.hyundaiCanfd, 44) == 0
  safety.init_tests()
  safety.set_alternative_experience(0)
  safety.set_controls_allowed(True)
  for _ in range(15):
    car.tick()
    frame = car.lfa()
    assert safety.safety_tx_hook(native(frame))
  assert abs(torque(frame)) >= 20
  # Exercise the actual native violation path, which resets its torque reference.
  bad = car.packer.make_can_msg("LFA", 0, {"TORQUE_REQUEST": 271, "STEER_REQ": 1})
  assert not safety.safety_tx_hook(native(bad))
  car.tick(extra=[(bad[0], bad[1], 192)])
  recovered = car.lfa()
  assert abs(torque(recovered)) <= 2
  assert safety.safety_tx_hook(native(recovered))
  # The patch does not grant controls or bypass safety during an actual inhibit.
  safety.set_controls_allowed(False)
  car.tick()
  assert not safety.safety_tx_hook(native(car.lfa()))


@pytest.mark.parametrize("address,src,length", [(0x12A, 128, 16), (0x12A, 194, 16), (0x12A, 2, 16),
                                               (0x1A0, 192, 32), (0x12A, 192, 8)])
def test_other_echoes_do_not_reset_torque_ramp(address, src, length):
  car = Car()
  car.ready()
  for _ in range(12):
    car.tick()
    before = car.lfa()
  car.tick(extra=[(address, bytes(length), src)])
  assert abs(torque(car.lfa())) >= abs(torque(before))


def test_replaying_old_rejection_cannot_repeatedly_reset_limiter():
  car = Car()
  car.ready()
  for _ in range(12):
    car.tick()
    car.lfa()
  car.tick(extra=[(0x12A, bytes(16), 192)])
  old = car.now
  assert abs(torque(car.lfa())) <= 2
  car.ci.update([(old, [(0x12A, bytes(16), 192)])])
  assert abs(torque(car.lfa())) >= 4


def test_rejection_survives_updates_without_apply_and_is_consumed_once():
  car = Car()
  car.ready()
  for _ in range(12):
    car.tick()
    car.lfa()
  car.tick(extra=[(0x12A, bytes(16), 192)])
  car.tick()  # Card need not receive a new CarControl/apply this cycle.
  assert abs(torque(car.lfa())) <= 2
  car.tick()
  assert abs(torque(car.lfa())) >= 4
