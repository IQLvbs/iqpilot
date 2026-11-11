import pytest

from iqdbc.car.hyundai.values import HyundaiSafetyFlags
from iqdbc.car.structs import CarParams
from iqdbc.safety.tests.hyundai_common import TESTER_PRESENT, canfd_accel, canfd_steer, packet
from iqdbc.safety.tests.libsafety import libsafety_py


@pytest.fixture
def safety():
  return libsafety_py.libsafety


@pytest.mark.parametrize("param", (
  0,
  HyundaiSafetyFlags.EV_GAS,
  HyundaiSafetyFlags.HYBRID_GAS,
  HyundaiSafetyFlags.LONG,
  HyundaiSafetyFlags.CAMERA_SCC,
  HyundaiSafetyFlags.CANFD_LKA_STEERING,
  HyundaiSafetyFlags.CANFD_ALT_BUTTONS,
  HyundaiSafetyFlags.CANFD_LKA_STEERING | HyundaiSafetyFlags.CANFD_LKA_STEERING_ALT,
  HyundaiSafetyFlags.CANFD_LKA_STEERING | HyundaiSafetyFlags.LONG,
  HyundaiSafetyFlags.CANFD_LKA_STEERING | HyundaiSafetyFlags.LONG | HyundaiSafetyFlags.CANFD_ALT_BUTTONS,
))
def test_canfd_safety_configurations_initialize(safety, param):
  assert safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, param) == 0
  safety.init_tests()
  assert safety.get_current_safety_param() == param


@pytest.mark.parametrize(("param", "addr", "length"), (
  (0, 0x12A, 16),
  (HyundaiSafetyFlags.CANFD_LKA_STEERING, 0x50, 16),
  (HyundaiSafetyFlags.CANFD_LKA_STEERING | HyundaiSafetyFlags.CANFD_LKA_STEERING_ALT, 0x110, 32),
  (HyundaiSafetyFlags.CANFD_LKA_STEERING | HyundaiSafetyFlags.LONG, 0x12A, 16),
))
def test_canfd_steering_limits(safety, param, addr, length):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, param)
  safety.init_tests()

  safety.set_controls_allowed(False)
  assert safety.safety_tx_hook(canfd_steer(addr, length, 0, False))
  assert not safety.safety_tx_hook(canfd_steer(addr, length, 1))

  safety.set_controls_allowed(True)
  assert safety.safety_tx_hook(canfd_steer(addr, length, 2))
  safety.set_desired_torque_last(270)
  safety.set_rt_torque_last(270)
  assert safety.safety_tx_hook(canfd_steer(addr, length, 270))
  assert not safety.safety_tx_hook(canfd_steer(addr, length, 271))
  assert not safety.safety_tx_hook(canfd_steer(addr, length, -271))


def test_canfd_tx_whitelist_and_buttons(safety):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, 0)
  safety.init_tests()
  assert not safety.safety_tx_hook(packet(0x123, 0, 8))
  assert not safety.safety_tx_hook(packet(0x12A, 1, 16))

  safety.set_controls_allowed(False)
  assert not safety.safety_tx_hook(packet(0x1CF, 0, 8, {2: 1}))
  assert not safety.safety_tx_hook(packet(0x1CF, 0, 8, {2: 2}))
  assert not safety.safety_tx_hook(packet(0x1CF, 0, 8, {2: 4}))

  safety.set_controls_allowed(True)
  assert safety.safety_tx_hook(packet(0x1CF, 0, 8, {2: 1}))
  assert not safety.safety_tx_hook(packet(0x1CF, 0, 8, {2: 2}))
  assert safety.safety_tx_hook(packet(0x1CF, 0, 8, {2: 4}))

  safety.set_controls_allowed(False)
  safety.set_cruise_engaged_prev(True)
  assert safety.safety_tx_hook(packet(0x1CF, 0, 8, {2: 4}))


def test_canfd_camera_scc_button_passthrough(safety):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, HyundaiSafetyFlags.CAMERA_SCC)
  safety.init_tests()

  safety.set_controls_allowed(False)
  assert safety.safety_tx_hook(packet(0x1CF, 2, 8))
  assert not safety.safety_tx_hook(packet(0x1CF, 0, 8))
  assert not safety.safety_tx_hook(packet(0x1CF, 2, 8, {2: 1}))
  assert not safety.safety_tx_hook(packet(0x1CF, 2, 8, {2: 2}))
  assert not safety.safety_tx_hook(packet(0x1CF, 2, 8, {2: 4}))

  safety.set_controls_allowed(True)
  assert safety.safety_tx_hook(packet(0x1CF, 2, 8, {2: 1}))
  assert not safety.safety_tx_hook(packet(0x1CF, 2, 8, {2: 2}))
  assert safety.safety_tx_hook(packet(0x1CF, 2, 8, {2: 4}))


def test_canfd_camera_scc_single_owner_forwarding(safety):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, HyundaiSafetyFlags.CAMERA_SCC)
  safety.init_tests()
  safety.set_timer(1_000_000)

  assert safety.safety_fwd_hook(2, 0x12A) == -1
  assert safety.safety_fwd_hook(2, 0x1E0) == -1
  assert safety.safety_fwd_hook(2, 0x1A0) == 0
  assert safety.safety_fwd_hook(0, 0xEA) == -1
  assert safety.safety_fwd_hook(0, 0x2AF) == -1
  assert safety.safety_tx_hook(packet(0xEA, 2, 24))
  assert safety.safety_tx_hook(packet(0x2AF, 2, 8))
  assert not safety.safety_tx_hook(packet(0xEA, 0, 24))
  assert not safety.safety_tx_hook(packet(0x2AF, 0, 8))


def test_canfd_camera_scc_longitudinal_single_owner_forwarding(safety):
  param = HyundaiSafetyFlags.CAMERA_SCC | HyundaiSafetyFlags.LONG
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, param)
  safety.init_tests()
  safety.set_timer(1_000_000)

  assert safety.safety_fwd_hook(2, 0x12A) == -1
  assert safety.safety_fwd_hook(2, 0x1A0) == -1
  assert safety.safety_fwd_hook(0, 0x175) == -1
  assert safety.safety_fwd_hook(0, 0xEA) == -1
  assert safety.safety_fwd_hook(0, 0x2AF) == -1
  assert safety.safety_tx_hook(packet(0xEA, 2, 24))
  assert safety.safety_tx_hook(packet(0x2AF, 2, 8))


def test_canfd_camera_scc_forwards_every_frame_openpilot_does_not_replace(safety):
  param = HyundaiSafetyFlags.CAMERA_SCC | HyundaiSafetyFlags.LONG
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, param)
  safety.init_tests()
  safety.set_timer(1_000_000)

  # openpilot sends these, so the stock frames must stay off the destination bus
  for addr in (0x12A, 0x1A0, 0x1E0):
    assert safety.safety_fwd_hook(2, addr) == -1
  for addr in (0x175, 0x1CF):
    assert safety.safety_fwd_hook(0, addr) == -1

  # openpilot doctors these for the camera, so the stock frame must not also reach it
  assert safety.safety_fwd_hook(0, 0xEA) == -1
  assert safety.safety_fwd_hook(0, 0x2AF) == -1

  # openpilot never sends these on a camera-SCC car, so blocking them strands the ECUs
  assert safety.safety_fwd_hook(2, 0x160) == 0
  assert safety.safety_fwd_hook(0, 0x1AA) == 2
  assert safety.safety_fwd_hook(2, 0x11A) == 0
  assert safety.safety_fwd_hook(2, 0x1B5) == 0
  assert safety.safety_fwd_hook(2, 0x1FA) == 0
  assert safety.safety_fwd_hook(2, 0x2BA) == 0


def test_canfd_radar_scc_keeps_stock_camera_feedback(safety):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, 0)
  safety.init_tests()
  safety.set_timer(1_000_000)

  assert safety.safety_fwd_hook(0, 0xEA) == 2
  assert safety.safety_fwd_hook(0, 0x2AF) == 2
  assert not safety.safety_tx_hook(packet(0xEA, 2, 24))
  assert not safety.safety_tx_hook(packet(0x2AF, 2, 8))


def test_canfd_stock_longitudinal_only_allows_cancel(safety):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, 0)
  safety.init_tests()
  assert safety.safety_tx_hook(canfd_accel(0, acc_mode=4))
  assert not safety.safety_tx_hook(canfd_accel(1, acc_mode=4))
  assert not safety.safety_tx_hook(canfd_accel(0, acc_mode=0))


def test_canfd_longitudinal_accel_limits(safety):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, HyundaiSafetyFlags.LONG)
  safety.init_tests()

  safety.set_controls_allowed(False)
  assert safety.safety_tx_hook(canfd_accel(0))
  assert not safety.safety_tx_hook(canfd_accel(1))

  safety.set_controls_allowed(True)
  for accel in (-400, 0, 250):
    assert safety.safety_tx_hook(canfd_accel(accel))
  for accel in (-401, 251):
    assert not safety.safety_tx_hook(canfd_accel(accel))


def test_canfd_hda2_diagnostic_payload_is_restricted(safety):
  param = HyundaiSafetyFlags.CANFD_LKA_STEERING | HyundaiSafetyFlags.LONG
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, param)
  safety.init_tests()
  assert safety.safety_tx_hook(packet(0x730, 1, 8, dict(enumerate(TESTER_PRESENT))))
  assert not safety.safety_tx_hook(packet(0x730, 1, 8, {0: 3, 1: 0x22}))


# SPAS2 turn signals: BLINKER_CONTROL is the top three bits of byte 16
SPAS2_NEUTRAL, SPAS2_LEFT, SPAS2_RIGHT = 0x00, 0x60, 0x80
SPAS2_PARAMS = (
  HyundaiSafetyFlags.CAMERA_SCC | HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS,
  # the Tucson it was tried on
  HyundaiSafetyFlags.CAMERA_SCC | HyundaiSafetyFlags.LONG | HyundaiSafetyFlags.CANFD_ALT_BUTTONS | HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS,
)


def spas2(blinker: int, bus: int = 0, length: int = 32, other: dict[int, int] | None = None):
  return packet(0x16A, bus, length, {16: blinker, **(other or {})})


@pytest.mark.parametrize("param", (
  0,
  HyundaiSafetyFlags.CAMERA_SCC,
  HyundaiSafetyFlags.CAMERA_SCC | HyundaiSafetyFlags.LONG | HyundaiSafetyFlags.CANFD_ALT_BUTTONS,
  HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS,  # HDA1 with radar SCC
  HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS | HyundaiSafetyFlags.LONG,
  HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS | HyundaiSafetyFlags.CANFD_LKA_STEERING,  # HDA2
  HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS | HyundaiSafetyFlags.CANFD_LKA_STEERING | HyundaiSafetyFlags.CAMERA_SCC | HyundaiSafetyFlags.LONG,
))
def test_canfd_spas2_needs_opt_in_on_hda1_camera_scc(safety, param):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, param)
  safety.init_tests()
  safety.set_controls_allowed(True)
  for blinker in (SPAS2_NEUTRAL, SPAS2_LEFT, SPAS2_RIGHT):
    assert not safety.safety_tx_hook(spas2(blinker))

  # and a parking ECU sending it is nobody's business here
  safety.safety_rx_hook(spas2(SPAS2_NEUTRAL))
  assert not safety.get_relay_malfunction()


@pytest.fixture
def aol(safety):
  """Always-on lateral, as the panda tracks it. Left switched off again for the other tests."""
  def set_lateral_allowed(allowed: bool):
    safety.set_aol_params(True, False, False)
    safety.set_controls_allowed_lat(allowed)
  yield set_lateral_allowed
  safety.set_controls_allowed_lat(False)
  safety.set_aol_params(False, False, False)


@pytest.mark.parametrize("param", SPAS2_PARAMS)
def test_canfd_spas2_direction_needs_the_steering_permission(safety, aol, param):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, param)
  safety.init_tests()

  # nothing engaged: neutral only, so a request can still be released
  safety.set_controls_allowed(False)
  aol(False)
  assert not safety.get_lat_active()
  assert safety.safety_tx_hook(spas2(SPAS2_NEUTRAL))
  assert not safety.safety_tx_hook(spas2(SPAS2_LEFT))
  assert not safety.safety_tx_hook(spas2(SPAS2_RIGHT))

  # cruise engaged, or cruise off with always-on lateral: the two cases where steering is allowed
  for controls_allowed, lateral_allowed in ((True, False), (False, True), (True, True)):
    safety.set_controls_allowed(controls_allowed)
    aol(lateral_allowed)
    assert safety.get_lat_active()
    for blinker in (SPAS2_NEUTRAL, SPAS2_LEFT, SPAS2_RIGHT):
      assert safety.safety_tx_hook(spas2(blinker))


@pytest.mark.parametrize("param", SPAS2_PARAMS)
def test_canfd_spas2_payload_is_limited_to_turn_signals(safety, param):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, param)
  safety.init_tests()
  safety.set_controls_allowed(True)

  # no hazards (0x20), no hazard button backlight (0x40), nothing in the low bits
  for blinker in range(256):
    assert safety.safety_tx_hook(spas2(blinker)) == (blinker in (SPAS2_NEUTRAL, SPAS2_LEFT, SPAS2_RIGHT))

  # bytes 0-2 are the checksum and counter, everything else stays empty
  assert safety.safety_tx_hook(spas2(SPAS2_RIGHT, other={0: 0xAB, 1: 0xCD, 2: 0xEF}))
  for index in range(3, 32):
    if index != 16:
      assert not safety.safety_tx_hook(spas2(SPAS2_NEUTRAL, other={index: 1}))
      assert not safety.safety_tx_hook(spas2(SPAS2_RIGHT, other={index: 0x80}))

  # car-side bus and full length only
  for bus, length in ((1, 32), (2, 32), (0, 24), (0, 48)):
    assert not safety.safety_tx_hook(spas2(SPAS2_RIGHT, bus=bus, length=length))


@pytest.mark.parametrize("param", SPAS2_PARAMS)
def test_canfd_spas2_must_be_the_only_sender(safety, param):
  safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, param)
  safety.init_tests()
  safety.set_controls_allowed(True)

  # nothing behind the relay may reach the car side on this address
  assert safety.safety_fwd_hook(2, 0x16A) == -1

  # the same address on another bus is not a conflict
  safety.safety_rx_hook(spas2(SPAS2_NEUTRAL, bus=2))
  assert not safety.get_relay_malfunction()
  assert safety.safety_tx_hook(spas2(SPAS2_RIGHT))

  # another sender on the car side is: stop everything
  safety.safety_rx_hook(spas2(SPAS2_NEUTRAL, bus=0))
  assert safety.get_relay_malfunction()
  assert not safety.safety_tx_hook(spas2(SPAS2_NEUTRAL))
  assert not safety.safety_tx_hook(spas2(SPAS2_RIGHT))


@pytest.mark.parametrize("param", SPAS2_PARAMS)
def test_canfd_spas2_leaves_the_other_rules_alone(safety, param):
  messages = (
    lambda: canfd_steer(0x12A, 16, 2),
    lambda: canfd_steer(0x12A, 16, 500),
    lambda: canfd_accel(100),
    lambda: canfd_accel(1000),
    lambda: packet(0xEA, 2, 24),
    lambda: packet(0x2AF, 2, 8),
    lambda: packet(0x165, 0, 24),  # SPAS1 stays blocked
    lambda: packet(0x123, 0, 8),
  )

  def decisions(safety_param, controls_allowed):
    safety.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, safety_param)
    safety.init_tests()
    safety.set_controls_allowed(controls_allowed)
    return [bool(safety.safety_tx_hook(message())) for message in messages] + \
           [safety.safety_fwd_hook(bus, addr) for bus in (0, 2) for addr in (0x12A, 0x1A0, 0xEA, 0x175, 0x4B9)]

  for controls_allowed in (False, True):
    assert decisions(param, controls_allowed) == decisions(param & ~HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS, controls_allowed)
