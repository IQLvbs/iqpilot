# Copyright (c) 2026 IQ.Pilot contributors. MIT License.
import ctypes
import fcntl
import struct
import unittest
from unittest.mock import MagicMock, call, patch

from panda.python import spi


class TestSpiDevice(unittest.TestCase):
  def setUp(self):
    self.file = MagicMock()
    self.file.fileno.return_value = 17
    self.transfers = []
    self.response = None
    self.short_transfer = False
    self.open = self.enterContext(patch('builtins.open', return_value=self.file))
    self.enterContext(patch.object(spi.os.path, 'exists', return_value=True))
    self.enterContext(patch.dict(spi.SPI_DEVICES, {}, clear=True))
    self.ioctl = self.enterContext(patch.object(fcntl, 'ioctl', side_effect=self.kernel_ioctl))
    self.flock = self.enterContext(patch.object(fcntl, 'flock'))
    self.device = spi.SpiDevice()

  def kernel_ioctl(self, fd, operation, data):
    self.assertEqual(fd, 17)
    if operation == spi.SpiDevice.SPI_IOC_WR_MAX_SPEED_HZ:
      return 0
    if operation == spi.SpiDevice.SPI_IOC_RD_BITS_PER_WORD:
      return b'\x08'
    self.assertEqual(operation, spi.SpiDevice.SPI_IOC_MESSAGE_1)
    self.assertEqual(len(data), 32)
    tx, rx, length, speed, delay, bits, cs, tx_nbits, rx_nbits, word_delay, padding = struct.unpack('=QQIIHBBBBBB', data)
    self.assertEqual((delay, bits, cs, tx_nbits, rx_nbits, word_delay, padding), (0, 8, 0, 0, 0, 0, 0))
    sent = ctypes.string_at(tx, length)
    self.transfers.append((speed, sent))
    response = self.response if self.response is not None else sent
    self.assertEqual(len(response), length)
    ctypes.memmove(rx, response, length)
    return length - int(self.short_transfer)

  def test_transfer_buffer_ownership(self):
    self.response = b'abc'
    view = self.device.xfer2(b'123')
    owned = self.device.xfer(b'456')
    self.response = b'xyz'
    self.device.xfer2(b'789')
    self.assertEqual(bytes(view), b'xyz')
    self.assertEqual(owned, b'abc')
    self.assertEqual(self.transfers, [(50000000, b'123'), (50000000, b'456'), (50000000, b'789')])

  def test_transfer_boundaries(self):
    for length in (1, 4096):
      with self.subTest(length=length):
        payload = bytes(length)
        self.assertEqual(bytes(self.device.xfer2(payload)), payload)
    for length in (0, 4097):
      with self.subTest(length=length), self.assertRaises(ValueError):
        self.device.xfer2(bytes(length))
    self.assertEqual(len(self.transfers), 2)

  def test_short_transfer(self):
    self.short_transfer = True
    with self.assertRaisesRegex(OSError, 'Short SPI transfer'):
      self.device.xfer(b'abc')

  def test_read_write(self):
    with patch.object(spi.os, 'read', return_value=b'abc') as read:
      self.assertEqual(self.device.readbytes(3), b'abc')
      read.assert_called_once_with(17, 3)
    with patch.object(spi.os, 'write', return_value=3) as write:
      self.device.writebytes([1, 2, 3])
      write.assert_called_once_with(17, b'\x01\x02\x03')

  def test_short_read_write(self):
    with patch.object(spi.os, 'read', return_value=b'a'), self.assertRaisesRegex(OSError, 'Short SPI read'):
      self.device.readbytes(2)
    with patch.object(spi.os, 'write', return_value=1), self.assertRaisesRegex(OSError, 'Short SPI write'):
      self.device.writebytes(b'ab')

  def test_read_write_boundaries(self):
    with patch.object(spi.os, 'read') as read, patch.object(spi.os, 'write') as write:
      for length in (0, 4097):
        with self.subTest(length=length):
          with self.assertRaises(ValueError):
            self.device.readbytes(length)
          with self.assertRaises(ValueError):
            self.device.writebytes(bytes(length))
      read.assert_not_called()
      write.assert_not_called()

  def test_shared_connections_and_bootloader_speed(self):
    other = spi.SpiDevice()
    self.open.assert_called_once_with(spi.DEV_PATH, 'r+b', buffering=0)
    bootloader = spi.SpiDevice(speed=1000000)
    self.assertEqual(self.open.call_count, 2)
    for device in (self.device, other, bootloader, self.device):
      device.xfer(b'a')
    self.assertEqual([speed for speed, _ in self.transfers], [50000000, 50000000, 1000000, 50000000])
    other.close()
    self.file.close.assert_not_called()

  def test_lock_released_after_transfer_failure(self):
    with self.assertRaisesRegex(RuntimeError, 'transfer failed'):
      with self.device.acquire() as device:
        self.assertIs(device, self.device)
        self.assertTrue(spi.SPI_LOCK.locked())
        raise RuntimeError('transfer failed')
    self.assertFalse(spi.SPI_LOCK.locked())
    self.flock.assert_has_calls([call(17, fcntl.LOCK_EX), call(17, fcntl.LOCK_UN)])

  def test_lock_acquisition_failure(self):
    self.flock.side_effect = OSError('lock failed')
    with self.assertRaisesRegex(OSError, 'lock failed'):
      with self.device.acquire():
        self.fail('acquired failed lock')
    self.assertFalse(spi.SPI_LOCK.locked())
    self.flock.assert_called_once_with(17, fcntl.LOCK_EX)

  def test_setup_failure_closes_file(self):
    self.ioctl.side_effect = OSError('setup failed')
    with self.assertRaisesRegex(OSError, 'setup failed'):
      spi.SpiDevice(speed=1000000)
    self.file.close.assert_called_once()
    self.assertNotIn(1000000, spi.SPI_DEVICES)
    self.assertFalse(spi.SPI_LOCK.locked())

  def test_missing_device(self):
    with patch.object(spi.os.path, 'exists', return_value=False), self.assertRaises(spi.PandaSpiUnavailable):
      spi.SpiDevice()

  def test_ack_is_copied_before_next_transfer(self):
    handle = spi.LegacyPandaSpiHandle()
    self.response = bytes([spi.DACK, 0, 0])
    ack = handle._wait_for_ack(self.device, spi.DACK, 100, 0x13, length=3)
    self.response = b'xyz'
    self.device.xfer2(b'123')
    self.assertEqual(ack, bytes([spi.DACK, 0, 0]))
