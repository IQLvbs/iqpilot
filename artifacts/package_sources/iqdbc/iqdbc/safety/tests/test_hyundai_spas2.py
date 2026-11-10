"""Feature admission/final-gate tests; no claim of ICU or physical priority."""
import binascii

import pytest

from iqdbc.car.structs import CarParams
from iqdbc.safety.tests.libsafety import libsafety_py

BASE = 44
FEATURE = 1024


def frame(control=0, counter=0, bus=0, length=32, updates=None):
  data = bytearray(length)
  if length > 2:
    data[2] = counter & 255
  if length > 16:
    data[16] = control << 5
  for i, value in (updates or {}).items():
    data[i] = value
  crc = binascii.crc_hqx(bytes(data[2:]) + b"\x6a\x01", 0) ^ 0x9F5B
  data[:2] = crc.to_bytes(2, "little")
  return libsafety_py.make_CANPacket(0x16A, bus, data)


def gear_frame(gear=5, counter=1, corrupt=False):
  data = bytearray(32)
  data[2], data[4] = counter & 255, gear
  crc = binascii.crc_hqx(bytes(data[2:]) + b"\x40\x00", 0) ^ 0x9F5B
  data[:2] = (crc ^ int(corrupt)).to_bytes(2, "little")
  return libsafety_py.make_CANPacket(0x40, 0, data)


@pytest.fixture
def s():
  lib = libsafety_py.libsafety
  assert lib.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, BASE | FEATURE) == 0
  lib.init_tests()
  lib.set_timer(1_000_000)
  lib.set_controls_allowed(True)
  return lib


def at(s, t, fresh=True):
  s.set_timer(t & 0xFFFFFFFF)
  if fresh:
    s.spas2_test_rx_context(True)


def prime(s, start=1_000_000, counter=0):
  for n in range(151):
    at(s, start + n * 20_000)
    assert s.safety_tx_hook(frame(0, counter + n))
  return start + 3_020_000, (counter + 151) & 255


@pytest.mark.parametrize("param", [0, 44, 1024, 16 | 1024, 8 | 16 | 1024])
def test_capability_does_not_broaden_other_profiles(s, param):
  s.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, param)
  s.init_tests()
  assert not s.spas2_test_enabled()
  assert not s.safety_tx_hook(frame())


@pytest.mark.parametrize("param", [8 | 1024, 8 | 4 | 1024, 44 | 1024])
def test_only_camera_scc_dedicated_profiles(s, param):
  s.set_safety_hooks(CarParams.SafetyModel.hyundaiCanfd, param)
  s.init_tests()
  s.set_timer(1_000_000)
  s.spas2_test_rx_context(True)
  assert s.spas2_test_enabled()
  assert s.safety_tx_hook(frame())
  assert not s.safety_tx_hook(frame(bus=1))


def test_start_requires_continuous_neutral_priming(s):
  at(s, 1_000_000)
  assert not s.safety_tx_hook(frame(4, 0))
  t, c = prime(s, counter=1)
  at(s, t)
  right = frame(4, c)
  assert s.safety_tx_hook(right)
  assert s.spas2_test_packet_valid(right)
  assert not s.spas2_test_packet_valid(frame(4, c - 1))


@pytest.mark.parametrize("mutation", [{3: 1}, {15: 1}, {16: 0xE0}, {31: 1}])
def test_reserved_shape_is_denied_even_with_good_crc(s, mutation):
  assert not s.safety_tx_hook(frame(updates=mutation))


def test_bad_crc_and_extended_rejected(s):
  bad = frame()
  bad[0].data[0] ^= 1
  assert not s.safety_tx_hook(bad)
  bad = frame()
  bad[0].extended = 1
  assert not s.safety_tx_hook(bad)


def test_rate_rejection_advances_receipt_counter_without_lease(s):
  t, c = prime(s)
  at(s, t)
  right = frame(4, c)
  assert s.safety_tx_hook(right)
  at(s, t + 19_000)
  assert not s.safety_tx_hook(frame(4, c + 1))
  at(s, t + 40_000)
  latest = frame(4, c + 2)
  assert s.safety_tx_hook(latest)
  assert not s.spas2_test_packet_valid(right)
  assert s.spas2_test_packet_valid(latest)


def test_rate_rejected_neutral_cancels_direction_ticket(s):
  t, c = prime(s)
  at(s, t)
  right = frame(4, c)
  assert s.safety_tx_hook(right)
  at(s, t + 1_000)
  assert not s.safety_tx_hook(frame(0, c + 1))
  assert not s.spas2_test_packet_valid(right)


def test_final_gate_rechecks_rx_controls_lease_and_relay(s):
  t, c = prime(s)
  at(s, t)
  right = frame(4, c)
  assert s.safety_tx_hook(right)
  at(s, t + 100_001, fresh=False)
  assert not s.spas2_test_packet_valid(right)
  at(s, t + 120_000)
  assert not s.safety_tx_hook(frame(4, c + 1))
  t, c = prime(s, t + 140_000, c + 2)
  at(s, t)
  right = frame(4, c)
  assert s.safety_tx_hook(right)
  s.set_controls_allowed(False)
  assert not s.spas2_test_packet_valid(right)
  at(s, t + 20_000)
  neutral = frame(0, c + 1)
  assert s.safety_tx_hook(neutral)
  assert s.spas2_test_packet_valid(neutral)
  s.set_relay_malfunction(True)
  assert not s.spas2_test_packet_valid(neutral)


def test_epoch_cap_cannot_be_renewed_by_replacements_or_direction_change(s):
  t, c = prime(s)
  for n in range(500):
    at(s, t + n * 20_000)
    assert s.safety_tx_hook(frame(4, c + n))
  at(s, t + 10_000_000)
  assert not s.safety_tx_hook(frame(4, c + 500))
  at(s, t + 10_020_000)
  assert not s.safety_tx_hook(frame(3, c + 501))
  t2, c2 = prime(s, t + 10_040_000, c + 502)
  at(s, t2)
  assert s.safety_tx_hook(frame(3, c2))


def test_direction_flip_inhibits_until_new_neutral_drain(s):
  t, c = prime(s)
  at(s, t)
  assert s.safety_tx_hook(frame(4, c))
  at(s, t + 20_000)
  assert not s.safety_tx_hook(frame(3, c + 1))
  at(s, t + 40_000)
  assert not s.safety_tx_hook(frame(4, c + 2))


def test_board_invalidation_and_stock_sender_conflict(s):
  t, c = prime(s)
  at(s, t)
  right = frame(4, c)
  assert s.safety_tx_hook(right)
  s.spas2_test_invalidate()
  assert not s.spas2_test_packet_valid(right)
  # Bus2 reflection must not be mistaken for a second car-side sender.
  s.safety_rx_hook(libsafety_py.make_CANPacket(0x16A, 2, bytes(32)))
  at(s, t + 20_000)
  assert s.safety_tx_hook(frame(0, c + 1))
  s.safety_rx_hook(libsafety_py.make_CANPacket(0x165, 0, bytes(24)))
  at(s, t + 40_000)
  assert not s.safety_tx_hook(frame(0, c + 2))


def test_optional_gear_observer_checks_crc_and_counter_without_global_rx_change(s):
  at(s, 1_000_000)
  s.spas2_test_reset_gear()
  s.safety_rx_hook(gear_frame(counter=17))
  assert s.safety_tx_hook(frame())
  # Repeating the gear counter invalidates feature priming, not normal controls.
  s.safety_rx_hook(gear_frame(counter=17))
  assert s.get_controls_allowed()
  at(s, 1_020_000, fresh=False)
  assert s.safety_tx_hook(frame(0, 1))  # neutral remains a release candidate


@pytest.mark.parametrize("gear", [0, 1, 2, 3, 4, 6, 7])
def test_non_drive_gear_denies_direction_but_not_neutral(s, gear):
  t, c = prime(s)
  at(s, t)
  s.spas2_test_reset_gear()
  s.safety_rx_hook(gear_frame(gear, counter=18))
  assert not s.safety_tx_hook(frame(4, c))
  s.set_timer(t + 20_000)
  assert s.safety_tx_hook(frame(0, c + 1))


@pytest.mark.parametrize("kind", range(5))
def test_every_mandatory_rx_health_failure_stops_direction(s, kind):
  t, c = prime(s)
  at(s, t)
  right = frame(4, c)
  assert s.safety_tx_hook(right)
  s.spas2_test_bad_rx(kind)
  assert not s.spas2_test_packet_valid(right)
  assert s.get_controls_allowed()  # feature failure does not rewrite base policy


def test_neutral_near_epoch_cap_completes_one_drain(s):
  t, c = prime(s)
  for n in range(499):
    at(s, t + n * 20_000)
    assert s.safety_tx_hook(frame(4, c + n))
  t2, c2 = prime(s, t + 9_980_000, c + 499)
  at(s, t2)
  assert s.safety_tx_hook(frame(3, c2))


def test_missing_accepted_neutral_resets_priming_despite_valid_receipts(s):
  at(s, 1_000_000)
  assert s.safety_tx_hook(frame(0, 0))
  # A two-message neutral span with many valid rate-rejected directional
  # receipts is not a continuous accepted neutral drain.
  for n in range(1, 151):
    at(s, 1_000_000 + n * 20_000)
    assert not s.safety_tx_hook(frame(4, n))
  at(s, 4_020_000)
  assert s.safety_tx_hook(frame(0, 151))
  at(s, 4_040_000)
  assert not s.safety_tx_hook(frame(4, 152))


def test_timer_and_counter_wrap_preserve_lease_and_epoch(s):
  t, c = prime(s, start=0xFFF00000, counter=240)
  at(s, t & 0xFFFFFFFF)
  right = frame(4, c)
  assert s.safety_tx_hook(right)
  s.set_timer((t + 100_001) & 0xFFFFFFFF)
  assert not s.spas2_test_packet_valid(right)


def test_real_optional_gear_drive_crc_sequence_and_change_at_final_gate(s):
  t, c = prime(s)
  at(s, t)
  s.spas2_test_reset_gear()
  s.safety_rx_hook(gear_frame(counter=255))
  right = frame(4, c)
  assert s.safety_tx_hook(right)
  s.set_timer(t + 1_000)
  s.safety_rx_hook(gear_frame(counter=0))
  assert s.spas2_test_packet_valid(right)
  s.set_timer(t + 2_000)
  s.safety_rx_hook(gear_frame(gear=0, counter=1))
  assert not s.spas2_test_packet_valid(right)


@pytest.mark.parametrize("bad", [gear_frame(counter=2), gear_frame(counter=1, corrupt=True)])
def test_bad_optional_gear_cannot_admit_direction(s, bad):
  t, c = prime(s)
  at(s, t)
  s.spas2_test_reset_gear()
  s.safety_rx_hook(gear_frame(counter=0))
  s.safety_rx_hook(bad)
  assert not s.safety_tx_hook(frame(4, c))


def test_board_forwarded_sender_conflict_latches_without_affecting_base_controls(s):
  t, c = prime(s)
  at(s, t)
  right = frame(4, c)
  assert s.safety_tx_hook(right)
  s.spas2_test_sender_conflict()
  assert not s.spas2_test_packet_valid(right)
  at(s, t + 20_000)
  assert not s.safety_tx_hook(frame(0, c + 1))
  assert s.get_controls_allowed()


def test_transient_non_drive_cannot_be_hidden_by_same_batch_drive_recovery(s):
  t, c = prime(s)
  at(s, t)
  s.spas2_test_reset_gear()
  s.safety_rx_hook(gear_frame(counter=10))
  assert s.safety_tx_hook(frame(4, c))
  s.set_timer(t + 1_000)
  s.safety_rx_hook(gear_frame(gear=0, counter=11))
  s.safety_rx_hook(gear_frame(gear=5, counter=12))
  at(s, t + 20_000)
  assert not s.safety_tx_hook(frame(4, c + 1))


def test_transient_mandatory_rx_fault_cannot_be_hidden_by_later_good_context(s):
  t, c = prime(s)
  at(s, t)
  assert s.safety_tx_hook(frame(4, c))
  # Bad CRC on the selected mandatory gas frame invalidates the feature now.
  assert not s.safety_rx_hook(libsafety_py.make_CANPacket(0x35, 0, bytes(32)))
  at(s, t + 20_000)
  assert not s.safety_tx_hook(frame(4, c + 1))
