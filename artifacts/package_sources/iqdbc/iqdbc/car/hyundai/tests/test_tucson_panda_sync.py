"""Tucson camera-SCC: the replaced messages are ready before the relay closes, and lateral follows the panda's own rules."""
import pytest

from iqdbc.can import CANPacker
from iqdbc.car import gen_empty_fingerprint, structs
from iqdbc.car.hyundai.carstate import LFA_REJECT_LIMIT
from iqdbc.car.hyundai.interface import CarInterface
from iqdbc.car.hyundai.values import CAR, DBC, Buttons, HyundaiFlags
from iqpilot.common.params import Params

TUCSON_FLAGS = HyundaiFlags.CANFD | HyundaiFlags.CANFD_ALT_BUTTONS | HyundaiFlags.CANFD_ALT_GEARS | HyundaiFlags.CANFD_CAMERA_SCC
DT_NS = 10_000_000
LFA = 0x12a
REJECTED = 192
RETURNED = 128


class Car:
  def __init__(self, monkeypatch, tmp_path, candidate=CAR.HYUNDAI_TUCSON_4TH_GEN, flags=TUCSON_FLAGS):
    monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
    Params().put_bool("ControlsReady", False)
    fingerprint = gen_empty_fingerprint()
    cp = CarInterface.get_params(candidate, fingerprint, [], True, False, False)
    cp.flags = int(flags)
    cp.openpilotLongitudinalControl = True
    cp_iq = CarInterface.get_params_iq(cp, candidate, fingerprint, [], True, False, False)
    self.ci = CarInterface(cp, cp_iq)
    self.packer = CANPacker(DBC[candidate]["pt"])
    self.t = 0
    self.adaptive = self.normal = self.button = self.brake = self.camera_main = self.acc_req = 0
    self.kph = 0.0
    self.ret = None

  @property
  def cs(self):
    return self.ci.CS

  def _msg(self, name, bus, **values):
    addr, dat, _ = self.packer.make_can_msg(name, bus, values)
    return addr, dat, bus

  def frames(self):
    speeds = {f"WHEEL_SPEED_{i}": self.kph for i in range(1, 5)}
    return [
      self._msg("CRUISE_BUTTONS_ALT", 0, ADAPTIVE_CRUISE_MAIN_BTN=self.adaptive, NORMAL_CRUISE_MAIN_BTN=self.normal, CRUISE_BUTTONS=self.button),
      self._msg("TCS", 0, DriverBraking=self.brake, ACC_REQ=self.acc_req),
      self._msg("WHEEL_SPEEDS", 0, **speeds),
      self._msg("MDPS", 0, STEERING_COL_TORQUE=0, STEERING_OUT_TORQUE=0),
      self._msg("LFA", 2),
      self._msg("SCC_CONTROL", 2, MainMode_ACC=self.camera_main),
      self._msg("LFAHDA_CLUSTER", 2),
    ]

  def tick(self, n=1, extra=()):
    for _ in range(n):
      self.t += DT_NS
      self.ret, _ = self.ci.update([(self.t, self.frames() + list(extra))])
    return self.ret

  def ready(self):
    self.tick(3)
    Params().put_bool("ControlsReady", True)
    self.tick(205)

  def press(self, attr, value=1):
    setattr(self, attr, value)
    self.tick()
    setattr(self, attr, 0)
    self.tick()

  def apply(self, lat=True, torque=0.15):
    cc = structs.CarControl()
    cc.latActive = lat
    cc.actuators.torque = torque if lat else 0.0
    _, sends = self.ci.apply(cc.as_reader(), structs.IQCarControl(), self.t)
    return sends

  def lfa(self, **kwargs):
    dat = next(d for a, d, b in self.apply(**kwargs) if a == LFA and b == 0)
    return (dat[6] >> 4) & 1, (((dat[6] & 0xF) << 7) | (dat[5] >> 1)) - 1024


@pytest.fixture
def car(monkeypatch, tmp_path):
  return Car(monkeypatch, tmp_path)


def test_replacements_are_ready_right_after_controls_ready(car):
  car.tick(3)
  assert car.cs.lfa is None and car.cs.mdps is None and car.cs.scc_control is None and car.cs.lfahda_cluster is None and car.cs.tcs is None
  Params().put_bool("ControlsReady", True)
  car.tick(2)
  assert None not in (car.cs.lfa, car.cs.mdps, car.cs.scc_control, car.cs.lfahda_cluster, car.cs.tcs)
  sent = set()
  for _ in range(6):
    car.tick()
    sent |= {(a, b) for a, _, b in car.apply(lat=False)}
  assert {(LFA, 0), (0x1a0, 0), (0x1e0, 0), (0xea, 2), (0x175, 2)} <= sent


def test_other_cars_keep_the_registration_ladder(monkeypatch, tmp_path):
  other = Car(monkeypatch, tmp_path, CAR.KIA_EV6, HyundaiFlags.CANFD | HyundaiFlags.CANFD_ALT_BUTTONS | HyundaiFlags.CANFD_CAMERA_SCC)
  assert not other.cs.panda_sync
  other.tick(3)
  Params().put_bool("ControlsReady", True)
  other.tick(2)
  assert other.cs.lfa is None


def test_main_follows_the_adaptive_press_like_the_panda(car):
  car.ready()
  assert not car.ret.cruiseState.available
  car.adaptive = 1
  car.tick()
  assert car.cs.main_enabled and car.cs.panda_main  # on the press, not the release
  car.adaptive = 0
  car.tick()
  assert car.cs.main_enabled and car.ret.cruiseState.available
  car.press("adaptive")
  assert not car.cs.main_enabled and not car.cs.panda_main
  car.tick()
  assert not car.ret.cruiseState.available


def test_holding_main_toggles_once(car):
  car.ready()
  car.adaptive = 1
  car.tick(50)
  assert car.cs.main_enabled and car.cs.panda_main
  car.adaptive = 0
  car.tick(5)
  assert car.cs.main_enabled and car.cs.panda_main


def test_normal_main_bit_is_ignored_like_the_panda(car):
  car.ready()
  car.press("normal")
  assert not car.cs.main_enabled and not car.cs.panda_main
  car.press("adaptive")
  car.normal = 1
  car.tick(80)
  car.normal = 0
  car.tick()
  assert car.cs.main_enabled and car.cs.panda_main


def test_camera_main_mode_cannot_force_lateral_on(car):
  car.ready()
  car.camera_main = 1
  car.tick(5)
  assert not car.cs.main_enabled and not car.ret.cruiseState.available


def test_presses_before_the_panda_is_in_safety_mode_do_not_count(car):
  car.tick(3)
  car.press("adaptive")
  assert not car.cs.panda_main and not car.cs.main_enabled


def test_set_holds_the_steering_request_until_release(car):
  car.ready()
  car.button = Buttons.SET_DECEL
  car.tick()
  assert car.cs.main_enabled and car.cs.lat_hold
  for _ in range(15):
    assert car.lfa() == (0, 0)
    car.tick()
  car.button = 0
  car.tick()
  assert not car.cs.lat_hold
  req, torque = car.lfa()
  assert req == 1 and abs(torque) <= 2
  for _ in range(5):
    car.tick()
    _, next_torque = car.lfa()
    assert abs(next_torque - torque) <= 2
    torque = next_torque
  assert torque != 0


def test_set_with_lateral_already_on_does_not_interrupt_steering(car):
  car.ready()
  car.press("adaptive")
  for _ in range(5):
    car.lfa()
    car.tick()
  car.button = Buttons.SET_DECEL
  car.tick()
  assert not car.cs.lat_hold
  assert car.lfa()[0] == 1


def test_set_while_braking_at_speed_stays_off(car):
  car.kph = 70.0
  car.brake = 1
  car.ready()
  car.press("button", Buttons.SET_DECEL)
  assert not car.cs.main_enabled and not car.cs.lat_hold


def test_set_while_braking_at_a_standstill_turns_on(car):
  car.brake = 1
  car.ready()
  car.press("button", Buttons.SET_DECEL)
  assert car.cs.main_enabled


def test_main_after_set_never_turns_on_against_the_panda(car):
  car.ready()
  car.press("button", Buttons.SET_DECEL)
  assert car.cs.main_enabled and not car.cs.panda_main
  car.press("adaptive")  # panda on, lateral off
  assert not car.cs.main_enabled and car.cs.panda_main
  car.press("adaptive")  # panda off, lateral stays off
  assert not car.cs.main_enabled and not car.cs.panda_main
  car.press("adaptive")  # both on
  assert car.cs.main_enabled and car.cs.panda_main


def test_rejected_frame_restarts_the_torque_ramp(car):
  car.ready()
  car.press("adaptive")
  for _ in range(20):
    car.tick()
    _, torque = car.lfa()
  assert abs(torque) >= 20
  car.tick(extra=[(LFA, b"\x00" * 16, REJECTED)])
  assert abs(car.lfa()[1]) <= 2
  assert car.cs.main_enabled


def test_sustained_rejection_turns_lateral_off_cleanly(car):
  car.ready()
  car.press("adaptive")
  for _ in range(LFA_REJECT_LIMIT):
    car.tick(extra=[(LFA, b"\x00" * 16, REJECTED)])
  car.tick()
  assert not car.cs.main_enabled and not car.ret.cruiseState.available and not car.cs.panda_main
  car.press("adaptive")
  assert car.cs.main_enabled and car.cs.panda_main


def test_brief_rejections_leave_lateral_on(car):
  car.ready()
  car.press("adaptive")
  for _ in range(5):
    car.tick(3, extra=[(LFA, b"\x00" * 16, REJECTED)])
    car.tick(extra=[(LFA, b"\x00" * 16, RETURNED)])
  assert car.cs.main_enabled


def test_sustained_rejection_with_cruise_engaged_keeps_cruise_available(car):
  car.acc_req = 1
  car.ready()
  car.press("button", Buttons.SET_DECEL)
  for _ in range(LFA_REJECT_LIMIT + 2):
    car.tick(extra=[(LFA, b"\x00" * 16, REJECTED)])
  assert car.cs.main_enabled
