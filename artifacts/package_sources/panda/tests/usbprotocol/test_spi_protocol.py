# Copyright (c) 2026 IQ.Pilot contributors. MIT License.
import binascii
import ctypes
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from panda import Panda
from panda.python import spi


class TestSpiProtocol(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.temp = tempfile.TemporaryDirectory()
    cls.addClassCleanup(cls.temp.cleanup)
    source = Path(cls.temp.name) / 'spi.c'
    source.write_text('''// Copyright (c) 2026 IQ.Pilot contributors. MIT License.
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#define MIN(a, b) ((a) < (b) ? (a) : (b))
static uint8_t uid[12];
#define UID_BASE uid
#define USB_PID 0xCC
uint8_t hw_type = 9;
#include "board/comms_definitions.h"
static uint16_t received;
static uint16_t queued_len;
static const uint8_t *queued;
static uint32_t executions;
int comms_control_handler(ControlPacket_t *req, uint8_t *resp) {
  (void)req;
  resp[0] = (uint8_t)++executions;
  return 1;
}
int comms_can_read(uint8_t *data, uint32_t len) {
  memset(data, 0x42, len);
  return len;
}
void comms_endpoint2_write(const uint8_t *data, uint32_t len) { (void)data; (void)len; executions++; }
void comms_can_write(const uint8_t *data, uint32_t len) { (void)data; (void)len; executions++; }
#include "board/drivers/spi.h"
void llspi_init(void) {}
void llspi_queue(const uint8_t *tx, uint16_t len) { queued = tx; queued_len = len; }
uint16_t llspi_rx_count(void) { return received; }
void exchange(const uint8_t *tx, uint8_t *rx, uint16_t len) {
  memset(rx, 0, len);
  memcpy(rx, queued, MIN(len, queued_len));
  memcpy(spi_buf_rx, tx, len);
  received = len;
  spi_cs_rising();
}
uint32_t execution_count(void) { return executions; }
''')
    library = Path(cls.temp.name) / 'spi.so'
    subprocess.run(['cc', '-shared', '-fPIC', *(['-Wl,-Bsymbolic'] if sys.platform == 'linux' else []), '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-I', str(Path(__file__).resolve().parents[2]), str(source), '-o', str(library)], check=True)
    cls.firmware = ctypes.CDLL(str(library))
    cls.firmware.exchange.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint16]
    cls.firmware.execution_count.restype = ctypes.c_uint32
    cls.firmware.spi_init()

  def setUp(self):
    self.handle = object.__new__(spi.PandaSpiHandle)

  def exchange(self, packet):
    result = ctypes.create_string_buffer(len(packet))
    self.firmware.exchange(bytes(packet), result, len(packet))
    return result.raw

  def test_duplicate_request_executes_once(self):
    before = self.firmware.execution_count()
    packet = spi.REQ_HEADER.pack(2, 0x12345, 3, spi.RESP_OVERHEAD) + b'abc'
    packet += spi.CRC.pack(binascii.crc32(packet))
    for _ in range(3):
      self.exchange(packet)
      response = self.exchange(bytes([spi.POLL]) * spi.RESP_OVERHEAD)
      self.assertEqual(spi.RESP_HEADER.unpack_from(response), (spi.ACK, 0x12345, 0))
      self.assertEqual(spi.CRC.unpack_from(response, spi.RESP_HEADER.size)[0], binascii.crc32(response[:-4]))
    self.assertEqual(self.firmware.execution_count(), before + 1)

  def test_can_write_retry_and_backpressure(self):
    before = self.firmware.execution_count()
    def request(req_id):
      packet = spi.REQ_HEADER.pack(3, req_id, 3, spi.RESP_OVERHEAD) + b'abc'
      packet += spi.CRC.pack(binascii.crc32(packet))
      self.exchange(packet)
      return spi.RESP_HEADER.unpack_from(self.exchange(bytes([spi.POLL]) * spi.RESP_OVERHEAD))[0]
    self.firmware.can_tx_comms_resume_spi()
    self.assertEqual(request(0x55551), spi.ACK)
    self.assertEqual(request(0x55551), spi.ACK)
    self.assertEqual(self.firmware.execution_count(), before + 1)
    self.assertEqual(request(0x55552), spi.NACK)
    self.firmware.can_tx_comms_resume_spi()
    self.assertEqual(request(0x55552), spi.NACK)
    self.assertEqual(request(0x55553), spi.ACK)
    self.assertEqual(self.firmware.execution_count(), before + 2)

  def test_firmware_and_python_interoperate(self):
    device = MagicMock()
    device.xfer2.side_effect = self.exchange
    device.xfer.side_effect = self.exchange
    response = self.handle._transfer_spidev(device, spi.INFO_ENDPOINT, 0x12346, b'', time.monotonic() + 1, 14, False)
    self.assertEqual(response, bytes(12) + b'\x09\xcc')

  def test_corrupt_request_has_no_side_effects(self):
    before = self.firmware.execution_count()
    packet = spi.REQ_HEADER.pack(2, 0x12347, 3, spi.RESP_OVERHEAD) + b'abc'
    packet += spi.CRC.pack(binascii.crc32(packet) ^ 1)
    self.exchange(packet)
    self.assertEqual(self.exchange(bytes([spi.POLL]) * spi.RESP_OVERHEAD)[0], spi.SLAVE_READY)
    self.assertEqual(self.firmware.execution_count(), before)

  def test_corrupt_response_retries_same_request(self):
    device = MagicMock()
    count = 0
    def read(packet):
      nonlocal count
      response = self.exchange(packet)
      count += 1
      return response[:-1] + bytes([response[-1] ^ 1]) if count == 1 else response
    device.xfer2.side_effect = self.exchange
    device.xfer.side_effect = read
    before = self.firmware.execution_count()
    response = self.handle._transfer_spidev(device, 2, 0x12348, b'abc', time.monotonic() + 1, 0, False)
    self.assertEqual(response, b'')
    self.assertEqual(self.firmware.execution_count(), before + 1)

  def test_bulk_read_respects_requested_length(self):
    for length in (1, 1013, 1014, 4032, 9000):
      with self.subTest(length=length):
        self.handle._transfer = MagicMock(side_effect=lambda endpoint, data, timeout, max_rx_len: bytes(max_rx_len))
        self.assertEqual(len(self.handle.bulkRead(1, length, 100)), length)
        self.assertLessEqual(max(c.kwargs['max_rx_len'] for c in self.handle._transfer.call_args_list), spi.XFER_SIZE)

  def test_new_firmware_discovery(self):
    info = bytes(range(12)) + b'\x09\xcc'
    with patch('panda.python.PandaSpiHandle') as modern, patch('panda.python.LegacyPandaSpiHandle', spi.LegacyPandaSpiHandle):
      modern.return_value.get_info.return_value = info
      result = Panda.spi_connect(None)
      self.assertIs(result[1], modern.return_value)
      self.assertEqual(result[2], info[:12].hex())
      self.assertFalse(result[3])

  def test_legacy_bootstub_discovery(self):
    info = bytes(range(12)) + b'\x09\xee\x02'
    legacy = object.__new__(spi.LegacyPandaSpiHandle)
    legacy.get_protocol_version = MagicMock(return_value=info)
    with (patch('panda.python.PandaSpiHandle') as modern,
          patch.object(spi.LegacyPandaSpiHandle, '__new__', return_value=legacy),
          patch.object(spi.LegacyPandaSpiHandle, '__init__', return_value=None)):
      modern.return_value.get_info.side_effect = spi.PandaSpiMissingAck
      result = Panda.spi_connect(None)
      self.assertIs(result[1], legacy)
      self.assertTrue(result[3])
      self.assertIsInstance(result[1], spi.PandaSpiHandle)
