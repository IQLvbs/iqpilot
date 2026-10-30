import math

from iqdbc.car.carlog import carlog
from iqdbc.can.dbc import DBC, Signal, SignalType


_packer_factory = None


def set_packer_factory(factory) -> None:
  global _packer_factory
  _packer_factory = factory


class _MessagePlan:
  def __init__(self, msg):
    self.msg = msg
    self.signals = list(msg.sigs.values())
    self.index = {name: i for i, name in enumerate(msg.sigs)}
    self.is_counter = [s.type == SignalType.COUNTER or s.name == "COUNTER" for s in self.signals]
    self.sig_counter = next((s for s in self.signals if s.type == SignalType.COUNTER or s.name == "COUNTER"), None)
    self.sig_checksum = next((s for s in self.signals if s.type > SignalType.COUNTER), None)
    factory = _packer_factory
    self.native = factory(self.signals) if factory is not None else None


class CANPacker:
  def __init__(self, dbc_name: str):
    self.dbc = DBC(dbc_name)
    self.counters: dict[int, int] = {}
    self._plans: dict[int, _MessagePlan] = {}

  def pack(self, address: int, values: dict[str, float]) -> bytearray:
    plan = self._plans.get(address)
    if plan is None:
      msg = self.dbc.addr_to_msg.get(address)
      if msg is None:
        carlog.error(f"msg not found for {address=}")
        return bytearray()
      plan = self._plans[address] = _MessagePlan(msg)
    msg = plan.msg
    dat = bytearray(msg.size)
    indices = []
    raw_values = []
    for name, value in values.items():
      i = plan.index.get(name)
      if i is None:
        carlog.error(f"unknown signal {name=} in {msg.name}")
        continue
      indices.append(i)
      raw_values.append(value)

    counter_set = False
    if plan.native is not None and plan.native(dat, indices, raw_values):
      for i, value in zip(indices, raw_values, strict=True):
        if plan.is_counter[i]:
          self.counters[address] = int(value)
          counter_set = True
    else:
      dat = bytearray(msg.size)
      for i, value in zip(indices, raw_values, strict=True):
        sig = plan.signals[i]
        ival = int(math.floor((value - sig.offset) / sig.factor + 0.5))
        if ival < 0:
          ival = (1 << sig.size) + ival
        set_value(dat, sig, ival)
        if plan.is_counter[i]:
          self.counters[address] = int(value)
          counter_set = True
    sig_counter = plan.sig_counter
    if sig_counter and not counter_set:
      if address not in self.counters:
        self.counters[address] = 0
      set_value(dat, sig_counter, self.counters[address])
      self.counters[address] = (self.counters[address] + 1) % (1 << sig_counter.size)
    sig_checksum = plan.sig_checksum
    if sig_checksum and sig_checksum.calc_checksum:
      checksum = sig_checksum.calc_checksum(address, sig_checksum, dat)
      set_value(dat, sig_checksum, checksum)
    return dat

  def make_can_msg(self, name_or_addr, bus: int, values: dict[str, float], rx_counter: int | None = None):
    if isinstance(name_or_addr, int):
      addr = name_or_addr
    else:
      msg = self.dbc.name_to_msg.get(name_or_addr)
      if msg is None:
        carlog.error(f"msg not found for {name_or_addr=}")
        return 0, b'', bus
      addr = msg.address
    pack_values = values if rx_counter is None else values | {"COUNTER": rx_counter}
    dat = self.pack(addr, pack_values)
    if len(dat) == 0:
      return 0, b'', bus
    return addr, bytes(dat), bus


def set_value(msg: bytearray, sig: Signal, ival: int) -> None:
  i = sig.lsb // 8
  bits = sig.size
  if sig.size < 64:
    ival &= (1 << sig.size) - 1
  while 0 <= i < len(msg) and bits > 0:
    shift = sig.lsb % 8 if (sig.lsb // 8) == i else 0
    size = min(bits, 8 - shift)
    mask = ((1 << size) - 1) << shift
    msg[i] &= ~mask
    msg[i] |= (ival & ((1 << size) - 1)) << shift
    bits -= size
    ival >>= size
    i = i + 1 if sig.is_little_endian else i - 1
