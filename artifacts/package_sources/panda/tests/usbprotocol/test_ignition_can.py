#!/usr/bin/env python3
import ctypes
import unittest

from panda.tests.libpanda import libpanda_py

lpp = libpanda_py.libpanda

IGNITION_CAN = ctypes.c_bool.in_dll(lpp, "ignition_can")
IGNITION_CAN_CNT = ctypes.c_uint32.in_dll(lpp, "ignition_can_cnt")

TESLA_LEGACY_ADDR = 0x348


def gtw_status(counter: int, drive_rail_req: bool, length: int = 8) -> bytes:
  dat = bytearray(length)
  dat[0] = 1 if drive_rail_req else 0
  dat[6] = counter & 0xF
  return bytes(dat)


class TestTeslaLegacyIgnition(unittest.TestCase):
  def setUp(self):
    IGNITION_CAN.value = False
    IGNITION_CAN_CNT.value = 7
    self._prime(0)
    IGNITION_CAN.value = False
    IGNITION_CAN_CNT.value = 7

  def _rx(self, bus: int, counter: int, drive_rail_req: bool, length: int = 8):
    pkt = libpanda_py.make_CANPacket(TESLA_LEGACY_ADDR, bus, gtw_status(counter, drive_rail_req, length))
    lpp.ignition_can_hook(pkt)

  def _prime(self, counter: int, bus: int = 0):
    self._rx(bus, counter, False)

  def test_ignition_follows_drive_rail_on_consecutive_counters(self):
    for bus in (0, 1):
      self._prime(0, bus)
      self._rx(bus, 1, True)
      self.assertTrue(IGNITION_CAN.value)
      self.assertEqual(IGNITION_CAN_CNT.value, 0)

      self._rx(bus, 2, False)
      self.assertFalse(IGNITION_CAN.value)

  def test_counter_wraps(self):
    self._prime(15)
    self._rx(0, 0, True)
    self.assertTrue(IGNITION_CAN.value)

  def test_non_consecutive_counter_is_ignored(self):
    self._prime(3)
    self._rx(0, 9, True)
    self.assertFalse(IGNITION_CAN.value)
    self.assertEqual(IGNITION_CAN_CNT.value, 7)

  def test_other_buses_are_ignored(self):
    self._prime(0)
    self._rx(2, 1, True)
    self.assertFalse(IGNITION_CAN.value)

  def test_wrong_length_is_ignored(self):
    self._prime(0)
    self._rx(0, 1, True, length=7)
    self.assertFalse(IGNITION_CAN.value)

  def test_cnt_resets_on_valid_frame(self):
    self._prime(4)
    IGNITION_CAN_CNT.value = 2
    self._rx(0, 5, False)
    self.assertEqual(IGNITION_CAN_CNT.value, 0)


DI_TORQUE2_ADDR = 0x116


def di_torque2(counter: int, gear: int, bad_checksum: bool = False) -> bytes:
  dat = bytearray(6)
  dat[1] = (gear & 0x7) << 4
  dat[4] = counter & 0xF
  dat[5] = (0x16 + 0x01 + sum(dat[:5])) & 0xFF
  if bad_checksum:
    dat[5] ^= 0x5A
  return bytes(dat)


class TestTeslaLegacyGearIgnition(unittest.TestCase):
  def setUp(self):
    IGNITION_CAN.value = False
    IGNITION_CAN_CNT.value = 7
    self.counter = 0
    for _ in range(6):
      self._rx(gear=1)
    IGNITION_CAN.value = False
    IGNITION_CAN_CNT.value = 7

  def _rx(self, gear: int, bus: int = 0, bad_checksum: bool = False, length: int = 6, counter: int | None = None):
    if counter is None:
      counter = self.counter
      self.counter += 1
    dat = di_torque2(counter, gear, bad_checksum)
    if length != 6:
      dat = (dat + bytes(8))[:length]
    lpp.ignition_can_hook(libpanda_py.make_CANPacket(DI_TORQUE2_ADDR, bus, dat))

  def test_out_of_park_gears_set_ignition(self):
    for gear in (2, 3, 4):
      IGNITION_CAN.value = False
      for _ in range(5):
        self._rx(gear)
      self.assertTrue(IGNITION_CAN.value, gear)
      self.assertEqual(IGNITION_CAN_CNT.value, 0)

  def test_park_and_invalid_gears_clear_ignition(self):
    for _ in range(5):
      self._rx(4)
    self.assertTrue(IGNITION_CAN.value)
    for gear in (1, 0, 5, 6, 7):
      IGNITION_CAN.value = True
      for _ in range(5):
        self._rx(gear)
      self.assertFalse(IGNITION_CAN.value, gear)

  def test_needs_a_streak_of_consecutive_counters(self):
    gap = (self.counter + 7) & 0xF
    self._rx(4, counter=gap)
    self.counter = gap + 1
    self._rx(4)
    self._rx(4)
    self.assertFalse(IGNITION_CAN.value)
    self._rx(4)
    self.assertTrue(IGNITION_CAN.value)

  def test_bad_checksum_never_sets_ignition(self):
    for _ in range(10):
      self._rx(4, bad_checksum=True)
    self.assertFalse(IGNITION_CAN.value)

  def test_a_gap_in_the_counter_restarts_the_streak(self):
    for _ in range(5):
      self._rx(4)
    IGNITION_CAN.value = False
    self._rx(4, counter=(self.counter + 5) & 0xF)
    self.assertFalse(IGNITION_CAN.value)

  def test_other_buses_and_lengths_are_ignored(self):
    for _ in range(6):
      self._rx(4, bus=1)
    for _ in range(6):
      self._rx(4, bus=2)
    for _ in range(6):
      self._rx(4, length=8)
    self.assertFalse(IGNITION_CAN.value)


if __name__ == "__main__":
  unittest.main()
