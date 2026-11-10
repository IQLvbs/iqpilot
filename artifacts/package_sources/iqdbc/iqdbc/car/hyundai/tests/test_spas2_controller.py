import hashlib
import json

import pytest

from iqdbc.can import CANPacker
from iqdbc.car import gen_empty_fingerprint, structs
from iqdbc.car.hyundai import spas2
from iqdbc.car.hyundai.interface import CarInterface
from iqdbc.car.hyundai.values import CAR, HyundaiFlags, HyundaiSafetyFlags
from iqpilot.common.params import Params

TEST_VIN = "5NM" + "A" * 6 + "R" + "0" * 7
START_NS = 10_000_000_000


@pytest.fixture
def identified_car(tmp_path, monkeypatch):
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path / "params"))
  fingerprint = gen_empty_fingerprint()
  fingerprint[0] = dict(spas2.REQUIRED_FRAMES)
  Params().put("FingerPrints", str(fingerprint))
  CP = CarInterface.get_params(CAR.HYUNDAI_TUCSON_4TH_GEN, fingerprint, [], True, False, False)
  CP.carVin = TEST_VIN
  assert CP.safetyConfigs[-1].safetyParam == 44
  return CP, fingerprint


@pytest.fixture
def qualification(tmp_path, monkeypatch):
  path = tmp_path / "qualification.json"
  monkeypatch.setattr(spas2, "QUALIFICATION_PATH", path)
  data = {
    "schema": spas2.QUALIFICATION_SCHEMA,
    "opt_in": True,
    "vin_sha256": hashlib.sha256(TEST_VIN.encode()).hexdigest(),
    "icu_part_number": spas2.ICU_PART_NUMBER,
    "driver_input_source": "BLINKERS_0x413_STALK",
    "neutral_release_verified": True,
    "self_timeout_verified": True,
    "receiver_timeout_ms": 500,
    "driver_priority_verified": True,
    "hazard_priority_verified": True,
    "stalk_fields_verified": True,
    "left_activation_verified": True,
    "right_activation_verified": True,
    "counter_gap_acceptance_verified": True,
    "moving_acceptance_verified": True,
    "navigation_trigger_cancel_verified": True,
    "evidence_sha256": hashlib.sha256(b"synthetic unit-test evidence only").hexdigest(),
  }
  return path, data


def write_record(qualification):
  path, data = qualification
  path.write_text(json.dumps(data))
  path.chmod(0o600)
  return path


@pytest.fixture
def qualified_car(identified_car, qualification):
  CP, fingerprint = identified_car
  write_record(qualification)
  CarInterface.configure_post_fingerprint(CP, fingerprint)
  assert CP.flags & HyundaiFlags.CANFD_SPAS2_BLINKERS
  assert CP.safetyConfigs[-1].safetyParam == 1068
  return CP, fingerprint


class Harness:
  """The real Hyundai interface, parsers, controller, Cap'n Proto and packer."""
  def __init__(self, CP):
    self.CI = CarInterface(CP, structs.IQCarParams())
    self.packer = CANPacker("hyundai_canfd_generated")
    self.CC = structs.CarControl.new_message()
    self.CC.enabled = self.CC.latActive = True
    self.CI.update([(START_NS - spas2.NEUTRAL_DRAIN_NS - 40_000_000, [])])  # Register dynamically read baseline messages.

  def feed(self, now=START_NS, stalk=(False, False), lamps=(False, False), omitted=(), corrupt=(), gear=5, src=0):
    frames = []
    for cp in self.CI.can_parsers.values():
      for address in cp.addresses:
        if address in omitted:
          continue
        values = {"GEAR": gear} if address == 0x40 else {}
        if address == 0x413:
          values = dict(zip(("LEFT_STALK", "RIGHT_STALK", "LEFT_LAMP", "RIGHT_LAMP"), (*stalk, *lamps), strict=True))
        message = self.packer.make_can_msg(cp.message_states[address].name, src if cp.bus == 0 else cp.bus, values)
        if address in corrupt:
          data = bytearray(message[1])
          data[0] ^= 0x01
          message = (message[0], bytes(data), message[2])
        frames.append(message)
    self.CI.update([(now, frames)])

  def request(self, now, left=False, right=False, valid=True, publisher=None):
    self.CC.leftBlinker, self.CC.rightBlinker = left, right
    self.CI.CC.set_car_control_context(now if publisher is None else publisher, valid)
    _, frames = self.CI.apply(self.CC.as_reader(), structs.IQCarControl(), now)
    return [frame for frame in frames if frame[0] in (0x165, 0x16A)]

  def arm(self, now=START_NS):
    self.feed(now)
    return self.request(now)

  def begin(self, now=START_NS, left=False, right=True, tick_ns=20_000_000):
    assert self.arm(now) == []
    started, sent = now, []
    while not self.CI.CC.spas2.active_control:
      now += tick_ns
      self.feed(now)
      sent += self.request(now, left=left, right=right)
      assert now - started < 3_250_000_000
    return now, sent


def controls(frames):
  assert all(address == 0x16A and len(data) == 32 and bus == 0 for address, data, bus in frames)
  return [(data[16] >> 5) & 7 for _, data, _ in frames]


def test_absent_record_never_enables_and_cached_bits_are_cleared(identified_car, qualification):
  CP, fingerprint = identified_car
  CP.flags = int(CP.flags) | int(HyundaiFlags.CANFD_SPAS2_BLINKERS)
  CP.safetyConfigs[-1].safetyParam = int(CP.safetyConfigs[-1].safetyParam) | int(HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS)
  CarInterface.configure_post_fingerprint(CP, fingerprint)
  assert not CP.flags & HyundaiFlags.CANFD_SPAS2_BLINKERS
  assert CP.safetyConfigs[-1].safetyParam == 44
  harness = Harness(CP)
  harness.arm()
  harness.feed(START_NS + 20_000_000)
  assert harness.request(START_NS + 20_000_000, right=True) == []


@pytest.mark.parametrize("field,value", [
  ("schema", "future-version"), ("opt_in", False), ("opt_in", 1), ("neutral_release_verified", False),
  ("self_timeout_verified", False), ("driver_priority_verified", False), ("hazard_priority_verified", False),
  ("stalk_fields_verified", False), ("driver_input_source", "LAMPS"), ("icu_part_number", "different"),
  ("left_activation_verified", False), ("right_activation_verified", False), ("counter_gap_acceptance_verified", False),
  ("moving_acceptance_verified", False), ("navigation_trigger_cancel_verified", False),
  ("vin_sha256", "0" * 64), ("evidence_sha256", "A" * 64), ("evidence_sha256", ""),
  ("receiver_timeout_ms", True), ("receiver_timeout_ms", 0), ("receiver_timeout_ms", 1001),
  ("receiver_timeout_ms", float("nan")), ("unexpected", True),
])
def test_qualification_rejects_unsupported_or_unproven_records(identified_car, qualification, field, value):
  CP, fingerprint = identified_car
  qualification[1][field] = value
  write_record(qualification)
  CarInterface.configure_post_fingerprint(CP, fingerprint)
  assert not CP.flags & HyundaiFlags.CANFD_SPAS2_BLINKERS
  assert CP.safetyConfigs[-1].safetyParam == 44


def test_qualification_requires_all_fields_and_private_regular_file(identified_car, qualification):
  CP, _ = identified_car
  path, data = qualification
  path.write_text(json.dumps(data))
  path.chmod(0o644)
  assert spas2.load_qualification(CP) is None
  path.chmod(0o600)
  assert spas2.load_qualification(CP) is not None
  target = path.with_suffix(".target")
  path.rename(target)
  path.symlink_to(target)
  assert spas2.load_qualification(CP) is None
  path.unlink()
  path.mkdir()
  assert spas2.load_qualification(CP) is None
  path.rmdir()
  path.write_text('{"schema":"duplicate","schema":"duplicate"}')
  path.chmod(0o600)
  assert spas2.load_qualification(CP) is None
  del data["hazard_priority_verified"]
  write_record(qualification)
  assert spas2.load_qualification(CP) is None


@pytest.mark.parametrize("flag", [HyundaiFlags.CANFD_HDA2, HyundaiFlags.HYBRID, HyundaiFlags.EV, HyundaiFlags.ENABLE_BLINKERS])
def test_qualification_never_broadens_platform_or_legacy_parking_path(identified_car, qualification, flag):
  CP, fingerprint = identified_car
  write_record(qualification)
  CP.flags = int(CP.flags) | int(flag)
  CarInterface.configure_post_fingerprint(CP, fingerprint)
  assert not CP.flags & HyundaiFlags.CANFD_SPAS2_BLINKERS


@pytest.mark.parametrize("change", ["unknown_vin", "other_vin", "wrong_year", "missing_frame", "wrong_dlc", "native_spas1", "native_spas2"])
def test_qualification_binds_identity_and_exact_observed_bus(identified_car, qualification, change):
  CP, fingerprint = identified_car
  write_record(qualification)
  if change == "unknown_vin":
    CP.carVin = ""
  elif change == "other_vin":
    CP.carVin = TEST_VIN[:-1] + "1"
  elif change == "wrong_year":
    CP.carVin = TEST_VIN[:9] + "S" + TEST_VIN[10:]
  elif change == "missing_frame":
    del fingerprint[0][0x413]
  elif change == "wrong_dlc":
    fingerprint[0][0x40] = 24
  elif change == "native_spas1":
    fingerprint[0][0x165] = 24
  else:
    fingerprint[0][0x16A] = 32
  CarInterface.configure_post_fingerprint(CP, fingerprint)
  assert not CP.flags & HyundaiFlags.CANFD_SPAS2_BLINKERS


def test_left_right_neutral_use_normal_controller_single_counter_and_no_ecu_disable(qualified_car, monkeypatch):
  CP, _ = qualified_car
  disabled = []
  monkeypatch.setattr("iqdbc.car.hyundai.interface.disable_ecu", lambda *args, **kwargs: disabled.append(kwargs))
  CarInterface.init(CP, structs.IQCarParams(), list, lambda _: None)
  assert disabled == []
  harness = Harness(CP)
  now, frames = harness.begin(left=True, right=False)
  assert controls(frames)[-1] == 3 and set(controls(frames)[:-1]) == {0}
  for _ in range(160):
    now += spas2.PERIOD_NS
    harness.feed(now)
    frames += harness.request(now)
  now, right_frames = harness.begin(now + spas2.PERIOD_NS)
  frames += right_frames
  assert controls(frames)[-1] == 4
  assert [data[2] for _, data, _ in frames] == [i % 256 for i in range(len(frames))]


def test_no_context_no_start_and_conflicting_requests_do_not_arm(qualified_car):
  harness = Harness(qualified_car[0])
  harness.feed()
  harness.CC.rightBlinker = True
  assert harness.CI.CC.spas2.update(harness.CC, harness.CI.CS, START_NS) is None
  now = START_NS + spas2.PERIOD_NS
  harness.feed(now)
  assert harness.request(now, left=True, right=True) == []
  now += spas2.PERIOD_NS
  harness.feed(now)
  assert harness.request(now, right=True) == []


@pytest.mark.parametrize("failure", ["publisher_stale", "publisher_future", "publisher_invalid", "disabled", "lateral_off",
                                     "stalk_left", "stalk_right", "both_stalks", "gear_park", "can_invalid", "can_timeout", "nonfinite_speed"])
def test_loss_of_active_authority_drains_once_and_requires_new_neutral_edge(qualified_car, failure):
  harness = Harness(qualified_car[0])
  now, _ = harness.begin()
  now += spas2.PERIOD_NS
  stalk = (failure in ("stalk_left", "both_stalks"), failure in ("stalk_right", "both_stalks"))
  harness.feed(now, stalk=stalk, gear=0 if failure == "gear_park" else 5)
  if failure == "disabled":
    harness.CC.enabled = False
  if failure == "lateral_off":
    harness.CC.latActive = False
  if failure == "can_invalid":
    harness.CI.CS.out.canValid = False
  if failure == "can_timeout":
    harness.CI.CS.out.canTimeout = True
  if failure == "nonfinite_speed":
    harness.CI.CS.out.vEgo = float("nan")
  publisher = now - spas2.SOURCE_LEASE_NS - 1 if failure == "publisher_stale" else now + 1 if failure == "publisher_future" else now
  assert controls(harness.request(now, right=True, valid=failure != "publisher_invalid", publisher=publisher)) == [0]
  harness.CC.enabled = harness.CC.latActive = True
  now += spas2.NEUTRAL_DRAIN_NS + spas2.NEUTRAL_MARGIN_NS + spas2.PERIOD_NS
  harness.feed(now)
  assert harness.request(now, right=True) == []


@pytest.mark.parametrize("address", [0x40, 0xA0, 0x175, 0x413])
def test_freshness_uses_accepted_frames_not_cached_canvalid(qualified_car, address):
  harness = Harness(qualified_car[0])
  now, _ = harness.begin()
  last_valid = now
  observed = []
  for _ in range(22):
    now += spas2.PERIOD_NS
    harness.feed(now, omitted=(address,))
    harness.CI.CS.out.canValid = True
    values = controls(harness.request(now, right=True))
    if now - last_valid > (spas2.STALK_LEASE_NS if address == 0x413 else spas2.VEHICLE_LEASE_NS):
      assert values in ([], [0])
    observed += values
  assert 0 in observed


@pytest.mark.parametrize("address", [0x40, 0xA0, 0x175])
def test_bad_checksum_does_not_refresh_required_input(qualified_car, address):
  harness = Harness(qualified_car[0])
  now, _ = harness.begin()
  observed = []
  for _ in range(7):
    now += spas2.PERIOD_NS
    harness.feed(now, corrupt=(address,))
    harness.CI.CS.out.canValid = True
    observed += controls(harness.request(now, right=True))
  assert observed[-1] == 0


def test_own_lamp_feedback_is_not_manual_stalk_intent(qualified_car):
  harness = Harness(qualified_car[0])
  now, _ = harness.begin()
  now += spas2.PERIOD_NS
  harness.feed(now, lamps=(False, True))
  harness.CI.CS.out.rightBlinker = True
  assert controls(harness.request(now, right=True)) == [4]


@pytest.mark.parametrize("source", [0, 128, 192])
def test_physical_stock_sender_latches_off_but_tx_echoes_do_not(qualified_car, source):
  harness = Harness(qualified_car[0])
  now, _ = harness.begin()
  now += spas2.PERIOD_NS
  harness.feed(now)
  harness.CI.update([(now, [(0x16A, bytes(32), source)])])
  assert controls(harness.request(now, right=True)) == ([] if source == 0 else [4])
  if source == 0:
    now += spas2.PERIOD_NS
    harness.feed(now)
    assert harness.request(now) == []


def test_direction_cap_starts_first_direction_and_held_true_never_rearms(qualified_car):
  harness = Harness(qualified_car[0])
  start, _ = harness.begin()
  for step in range(1, 501):
    now = start + step * spas2.PERIOD_NS
    harness.feed(now)
    assert controls(harness.request(now, right=True)) == ([4] if step < 500 else [0])
  for step in range(1, 161):
    now = start + spas2.DIRECTION_MAX_NS + step * spas2.PERIOD_NS
    harness.feed(now)
    assert controls(harness.request(now, right=True)) in ([], [0])
  assert not harness.CI.CC.spas2.active_control and not harness.CI.CC.spas2.pending_control
  now += spas2.PERIOD_NS
  harness.feed(now)
  assert harness.request(now, right=True) == []
  _, frames = harness.begin(now + spas2.PERIOD_NS)
  assert controls(frames)[-1] == 4 and set(controls(frames)[:-1]) == {0}


def test_short_scheduler_gap_has_no_catchup_burst_and_long_gap_expires_direction(qualified_car):
  harness = Harness(qualified_car[0])
  now, _ = harness.begin()
  now += 60_000_000
  harness.feed(now)
  assert controls(harness.request(now, right=True)) == [4]
  assert harness.request(now + 1, right=True) == []
  now += spas2.SOURCE_LEASE_NS + 2
  harness.feed(now)
  assert controls(harness.request(now, right=True)) == [0]


def test_original_publisher_timestamp_and_clock_regression_cannot_extend_request(qualified_car):
  harness = Harness(qualified_car[0])
  now, _ = harness.begin()
  old_source = now
  for _ in range(6):
    now += spas2.PERIOD_NS
    harness.feed(now)
    values = controls(harness.request(now, right=True, publisher=old_source))
  assert values == [0]
  assert harness.request(now - 10_000_000, right=True) == []


@pytest.mark.parametrize("abort", ["cancel", "reverse", "manual", "source", "can", "loop_gap"])
def test_pending_preamble_aborts_without_delayed_activation_or_held_true_restart(qualified_car, abort):
  harness = Harness(qualified_car[0])
  assert harness.arm() == []
  now = START_NS + spas2.PERIOD_NS
  harness.feed(now)
  assert controls(harness.request(now, right=True)) == [0]
  now += spas2.SOURCE_LEASE_NS + 1 if abort == "loop_gap" else spas2.PERIOD_NS
  harness.feed(now, stalk=(abort == "manual", False))
  if abort == "can":
    harness.CI.CS.out.canValid = False
  assert harness.request(now, left=abort == "reverse", right=abort not in ("cancel", "reverse"), valid=abort != "source") == []
  assert harness.CI.CC.spas2.pending_control == 0
  for _ in range(170):
    now += spas2.PERIOD_NS
    harness.feed(now)
    # Cancellation stays neutral; all other aborts retain the same directional level.
    assert harness.request(now, left=abort == "reverse", right=abort not in ("cancel", "reverse")) == []


@pytest.mark.parametrize("tick_ns", [20_000_000, 10_100_000])
def test_preamble_runs_full_margin_under_tick_jitter(qualified_car, tick_ns):
  harness = Harness(qualified_car[0])
  harness.arm()
  now = START_NS
  sent = []
  while not harness.CI.CC.spas2.active_control:
    now += tick_ns
    harness.feed(now)
    frames = harness.request(now, right=True)
    if frames:
      sent.append((now, controls(frames)[0]))
    assert now - START_NS < 3_250_000_000
  neutral = [timestamp for timestamp, value in sent if value == 0]
  assert spas2.NEUTRAL_DRAIN_NS < neutral[-1] - neutral[0] <= spas2.NEUTRAL_DRAIN_NS + spas2.NEUTRAL_MARGIN_NS
  assert sent[-1][1] == 4 and sent[-1][0] - neutral[-1] >= spas2.DIRECTION_START_GAP_NS
  assert all(spas2.PERIOD_NS <= after - before <= spas2.SOURCE_LEASE_NS for before, after in zip(neutral, neutral[1:], strict=False))


def test_long_idle_sends_nothing_then_requalifies_same_new_direction(qualified_car):
  harness = Harness(qualified_car[0])
  now = START_NS
  harness.arm(now)
  for _ in range(300):
    now += spas2.PERIOD_NS
    harness.feed(now)
    assert harness.request(now) == []
  now += spas2.PERIOD_NS
  harness.feed(now)
  assert controls(harness.request(now, right=True)) == [0]
  assert harness.CI.CC.spas2.pending_control == 4


@pytest.mark.parametrize("tick_ns,jitter", [(20_000_000, False), (10_100_000, False), (20_000_000, True)])
def test_actual_host_packer_sequence_is_accepted_by_native_safety(qualified_car, tick_ns, jitter):
  from pathlib import Path

  pytest.importorskip("cffi")
  library = Path(spas2.__file__).parents[2] / "safety/tests/libsafety/libsafety.so"
  if not library.exists():
    pytest.skip("build the native libsafety test library for the cross-layer test")
  from iqdbc.safety.tests.libsafety import libsafety_py

  safety = libsafety_py.libsafety
  assert safety.set_safety_hooks(structs.CarParams.SafetyModel.hyundaiCanfd, 1068) == 0
  safety.init_tests()
  safety.set_controls_allowed(True)
  harness = Harness(qualified_car[0])
  arrival_index = 0
  last_control = None
  directions = []

  def step(now, right=False):
    nonlocal arrival_index, last_control
    harness.feed(now)
    frames = harness.request(now, right=right)
    for address, data, bus in frames:
      delay_us = [5000, 0, 3000, 1000][arrival_index % 4] if jitter else 0
      arrival_index += 1
      safety.set_timer(((now // 1000) + delay_us) & 0xFFFFFFFF)
      safety.spas2_test_rx_context(True)
      packet = libsafety_py.make_CANPacket(address, bus, data)
      accepted = safety.safety_tx_hook(packet)
      value = controls(frames)[0]
      if value and last_control != value:
        assert accepted, (now, value, data[2])  # First directional request must actually cross the native gate.
      if accepted:
        assert safety.spas2_test_packet_valid(packet)
        if value:
          directions.append(now)
      elif not jitter:
        raise AssertionError((now, value, data[2]))
      last_control = value
    return controls(frames)

  now = START_NS
  assert step(now) == []
  # Idle lasts well beyond the native receipt lease, without neutral keepalives.
  for _ in range(50):
    now += tick_ns
    assert step(now) == []
  # A short cancelled request never becomes a delayed direction.
  now += tick_ns
  assert step(now, right=True) == [0]
  now += tick_ns
  assert step(now) == []
  for _ in range(330):
    now += tick_ns
    assert step(now) == []
  while not harness.CI.CC.spas2.active_control:
    now += tick_ns
    assert step(now, right=True) in ([], [0], [4])
  direction_start = now
  while now - direction_start <= spas2.DIRECTION_MAX_NS + spas2.NEUTRAL_DRAIN_NS + spas2.NEUTRAL_MARGIN_NS + tick_ns:
    now += tick_ns
    values = step(now, right=True)
    if values == [4]:
      assert now - direction_start < spas2.DIRECTION_MAX_NS
  assert directions
  now += spas2.PERIOD_NS
  assert step(now, right=True) == []
  # A new false edge arms one new preamble, including after native idle expiry.
  for _ in range(50):
    now += tick_ns
    assert step(now) == []
  previous_count = len(directions)
  while not harness.CI.CC.spas2.active_control:
    now += tick_ns
    step(now, right=True)
  assert len(directions) > previous_count


@pytest.mark.parametrize("qualified", [False, True])
def test_actual_get_car_selects_capability_only_after_identified_vin(identified_car, qualification, monkeypatch, qualified):
  from iqdbc.car import car_helpers

  _, fingerprint = identified_car
  if qualified:
    write_record(qualification)

  def identified_fingerprint(*args, **kwargs):
    return CAR.HYUNDAI_TUCSON_4TH_GEN, fingerprint, TEST_VIN, [], structs.CarParams.FingerprintSource.fixed, True

  monkeypatch.setattr(car_helpers, "fingerprint", identified_fingerprint)
  interface = car_helpers.get_car(list, lambda _: None, lambda _: None, True, False)
  assert interface.CP.carVin == TEST_VIN
  assert bool(interface.CP.flags & HyundaiFlags.CANFD_SPAS2_BLINKERS) is qualified
  assert bool(interface.CP.safetyConfigs[-1].safetyParam & HyundaiSafetyFlags.CANFD_SPAS2_BLINKERS) is qualified
  assert interface.CC.spas2.qualified is qualified
