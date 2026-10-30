import unittest, array, time, struct, ctypes
from unittest import mock
from tinygrad.helpers import mv_address
from tinygrad.runtime.support.hcq import MMIOInterface
from tinygrad.runtime.support.usb import USBMMIOInterface, USB3, CustomASM24Controller, USB_MAX_STREAM, alloc_cbuffer
from tinygrad.runtime.support.am.ip import AM_SDMA, AM_SMU
from tinygrad.runtime.autogen.am import am
from test.mockgpu.usb import MockUSB

class TestHCQIface(unittest.TestCase):
  def setUp(self):
    self.size = 4 << 10
    self.buffer = bytearray(self.size)
    self.mv = memoryview(self.buffer).cast('I')
    self.mmio = MMIOInterface(mv_address(self.mv), self.size, fmt='I')

  def test_getitem_setitem(self):
    self.mmio[1] = 0xdeadbeef
    self.assertEqual(self.mmio[1], 0xdeadbeef)
    values = array.array('I', [10, 20, 30, 40])
    self.mmio[2:6] = values
    read_slice = self.mmio[2:6]
    # self.assertIsInstance(read_slice, array.array)
    self.assertEqual(read_slice, values.tolist())
    self.assertEqual(self.mv[2:6].tolist(), values.tolist())

  def test_view(self):
    full = self.mmio.view()
    self.assertEqual(len(full), len(self.mmio))
    self.mmio[0] = 0x12345678
    self.assertEqual(full[0], 0x12345678)

    # offset-only view
    self.mmio[1] = 0xdeadbeef
    off = self.mmio.view(offset=4)
    self.assertEqual(off[0], 0xdeadbeef)

    # offset + size view: write into sub-view and confirm underlying buffer
    values = array.array('I', [11, 22, 33])
    sub = self.mmio.view(offset=8, size=12)
    sub[:] = values
    self.assertEqual(sub[:], values.tolist())
    self.assertEqual(self.mv[2:5].tolist(), values.tolist())

  def test_speed(self):
    start = time.perf_counter()
    for i in range(10000):
      self.mmio[3:100] = array.array('I', [i] * 97)
      _ = self.mmio[3:100]
    end = time.perf_counter()

    mvstart = time.perf_counter()
    for i in range(10000):
      self.mv[3:100] = array.array('I', [i] * 97)
      _ = self.mv[3:100].tolist()
    mvend = time.perf_counter()
    print(f"speed: hcq {end - start:.6f}s vs plain mv {mvend - mvstart:.6f}s")

class TestUSBMMIOInterface(unittest.TestCase):
  def setUp(self):
    self.size = 256
    self.buffer = bytearray(self.size)
    self.usb = MockUSB(self.buffer)
    self.mmio = USBMMIOInterface(self.usb, 0, self.size, fmt='B', pcimem=False)

  def test_getitem_setitem_byte(self):
    self.mmio[1] = 0xAB
    self.assertEqual(self.mmio[1], 0xAB)
    self.assertEqual(self.usb.mem[1], 0xAB)

  def test_slice_getitem_setitem(self):
    values = [1, 2, 3, 4]
    self.mmio[10:14] = values
    raw = self.mmio[10:14]
    self.assertIsInstance(raw, bytes)
    self.assertEqual(list(raw), values)
    self.assertEqual(list(self.usb.mem[10:14]), values)

  def test_view(self):
    self.mmio[0] = 5
    view = self.mmio.view(offset=1, size=3)
    self.assertEqual(view[0], self.usb.mem[1])
    view[:] = [7, 8, 9]
    self.assertEqual(list(self.usb.mem[1:4]), [7, 8, 9])
    full_view = self.mmio.view()
    self.assertEqual(len(full_view), len(self.mmio))
    self.mmio[2] = 0xFE
    self.assertEqual(full_view[2], 0xFE)

  def test_pcimem_dword(self):
    usb2 = MockUSB(bytearray(self.size))
    mmio_pci = USBMMIOInterface(usb2, 0, self.size, fmt='I', pcimem=True)
    mmio_pci[3] = 0x11223344
    self.assertEqual(mmio_pci[3], 0x11223344)
    self.assertEqual(usb2.mem[12:16], b'\x44\x33\x22\x11')

  def test_pcimem_slice(self):
    usb3 = MockUSB(bytearray(self.size))
    mmio_pci = USBMMIOInterface(usb3, 0, self.size, fmt='B', pcimem=True)
    values = [2, 3, 4, 5]
    mmio_pci[4:8] = values
    raw = mmio_pci[4:8]
    self.assertIsInstance(raw, bytes)
    self.assertEqual(list(raw), values)
    self.assertEqual(list(usb3.mem[4:8]), values)

class RecordingUSB:
  def __init__(self): self.ops = []
  def control_write(self, request, value=0, index=0, data=b'', timeout=1000): self.ops.append(("ctrl", request, value, index, bytes(data)))
  def bulk_write(self, payload, timeout=1000): self.ops.append(("bulk", bytes(payload)))

class TestASM24Streams(unittest.TestCase):
  def setUp(self):
    self.ctrl = CustomASM24Controller.__new__(CustomASM24Controller)
    self.ctrl.usb = RecordingUSB()

  def _streams(self):
    ops = self.ctrl.usb.ops
    return [(struct.unpack('<III', c[4]), c[3], b[1]) for c, b in zip(ops[::2], ops[1::2])]

  def test_pcie_mem_write_small_is_one_stream(self):
    self.ctrl.pcie_mem_write(0x1000, bytes(range(16)))
    self.assertEqual(self._streams(), [((0x1000, 0, 4), 1, bytes(range(16)))])

  def test_pcie_mem_write_splits_at_stream_limit(self):
    data = bytes(i & 0xff for i in range(2 * USB_MAX_STREAM + 64))
    self.ctrl.pcie_mem_write(0x1_0000_1000, data)
    streams = self._streams()
    self.assertEqual(len(streams), 3)
    for i, ((lo, hi, dwords), mode, payload) in enumerate(streams):
      self.assertEqual(mode, 1)
      self.assertEqual((hi << 32) | lo, 0x1_0000_1000 + i * USB_MAX_STREAM)
      self.assertEqual(dwords * 4, len(payload))
      self.assertLessEqual(len(payload), USB_MAX_STREAM)
    self.assertEqual(b"".join(p for _, _, p in streams), data)

class TestUSB3BulkRead(unittest.TestCase):
  def setUp(self):
    self.usb = USB3.__new__(USB3)
    self.usb.handle, self.usb._transferred = None, ctypes.c_int(0)
    self.usb._bulk_buf, self.usb._bulk_mv = alloc_cbuffer(0x1000)

  def _transfer(self, got):
    def fake(handle, ep, buf, length, transferred, timeout):
      transferred.value = got
      return 0
    return mock.patch("tinygrad.runtime.autogen.libusb.libusb_bulk_transfer", side_effect=fake)

  def test_full_read(self):
    with self._transfer(512): self.assertEqual(len(self.usb.bulk_read(512)), 512)

  def test_short_read_raises(self):
    with self._transfer(100), self.assertRaisesRegex(RuntimeError, "short read: 100/512"): self.usb.bulk_read(512)

class _Reg:
  def __init__(self, log, name): self.log, self.name = log, name
  def update(self, **kw): self.log.append((self.name, kw))

class _Adev:
  def __init__(self, ip_ver):
    self.ip_ver, self.log, self.devfmt = ip_ver, [], "mock"
  def reg(self, name): return _Reg(self.log, name)
  def is_hive(self): return False

class TestAMQuiesce(unittest.TestCase):
  def test_sdma_halt_gfx12(self):
    sdma = AM_SDMA.__new__(AM_SDMA)
    sdma.adev, sdma.sdma_name = _Adev({am.SDMA0_HWIP: (7,0,0)}), "MCU"
    sdma.halt_engines()
    self.assertEqual(sdma.adev.log, [("regSDMA0_MCU_CNTL", {"halt": 1})])

  def test_sdma_halt_skipped_before_v6(self):
    sdma = AM_SDMA.__new__(AM_SDMA)
    sdma.adev, sdma.sdma_name = _Adev({am.SDMA0_HWIP: (5,2,0)}), "F32"
    sdma.halt_engines()
    self.assertEqual(sdma.adev.log, [])

  def _smu(self, config_reads):
    smu = AM_SMU.__new__(AM_SMU)
    smu.adev = _Adev({am.MP0_HWIP: (14,0,2)})
    smu.adev.pci_dev = mock.Mock(read_config=mock.Mock(side_effect=config_reads))
    smu._send_msg = mock.Mock()
    return smu

  def test_mode1_reset_waits_for_config_space(self):
    smu = self._smu([0xffff, 0xffff, 0x1002])
    with mock.patch("tinygrad.runtime.support.am.ip.time.sleep"): smu.mode1_reset()
    self.assertEqual(smu.adev.pci_dev.read_config.call_count, 3)
    smu.adev.pci_dev.read_config.assert_called_with(0, 2)

  def test_mode1_reset_wedged_gpu_raises(self):
    smu = self._smu(lambda *_: 0xffff)
    with mock.patch("tinygrad.runtime.support.am.ip.time.sleep"), self.assertRaisesRegex(TimeoutError, "did not return from mode1 reset"):
      with mock.patch("tinygrad.helpers.time.perf_counter", side_effect=[0.0, 0.0, 5.0, 5.0]): smu.mode1_reset()

if __name__ == "__main__":
  unittest.main()
