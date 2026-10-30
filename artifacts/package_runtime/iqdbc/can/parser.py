import math
import numbers
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from iqdbc.car.carlog import carlog
from iqdbc.can.dbc import DBC, Signal


MAX_BAD_COUNTER = 5
CAN_INVALID_CNT = 5

_decoder_factory = None
_update_backend = None


def set_decoder_factory(factory) -> None:
  global _decoder_factory
  _decoder_factory = factory


def set_update_backend(backend) -> None:
  global _update_backend
  _update_backend = backend


def _segments(sig: Signal) -> tuple[tuple[int, int, int, int], ...]:
  segments = []
  i = sig.msb // 8
  bits = sig.size
  while i >= 0 and bits > 0:
    lsb = sig.lsb if (sig.lsb // 8) == i else i * 8
    msb = sig.msb if (sig.msb // 8) == i else (i + 1) * 8 - 1
    size = msb - lsb + 1
    segments.append((i, lsb - (i * 8), (1 << size) - 1, bits - size))
    bits -= size
    i = i - 1 if sig.is_little_endian else i + 1
  return tuple(segments)


def make_python_decoder(signals: list[Signal]):
  plans = tuple(
    (_segments(sig), sig.size - 1, 1 << sig.size, sig.is_signed, sig.factor, sig.offset)
    for sig in signals
  )

  def decode(dat: bytes) -> list[float]:
    length = len(dat)
    out = []
    for segments, sign_bit, sign_span, is_signed, factor, offset in plans:
      ret = 0
      for index, shift, mask, place in segments:
        if index >= length:
          break
        ret |= ((dat[index] >> shift) & mask) << place
      if is_signed:
        ret -= ((ret >> sign_bit) & 0x1) * sign_span
      out.append(ret * factor + offset)
    return out

  return decode


def get_raw_value(dat: bytes | bytearray, sig: Signal) -> int:
  ret = 0
  i = sig.msb // 8
  bits = sig.size
  while 0 <= i < len(dat) and bits > 0:
    lsb = sig.lsb if (sig.lsb // 8) == i else i * 8
    msb = sig.msb if (sig.msb // 8) == i else (i + 1) * 8 - 1
    size = msb - lsb + 1
    d = (dat[i] >> (lsb - (i * 8))) & ((1 << size) - 1)
    ret |= d << (bits - size)
    bits -= size
    i = i - 1 if sig.is_little_endian else i + 1
  return ret


@dataclass
class MessageState:
  address: int
  name: str
  size: int
  signals: list[Signal]
  ignore_alive: bool = False
  ignore_checksum: bool = False
  ignore_counter: bool = False
  frequency: float = 0.0
  timeout_threshold: float = 1e5  # default to 1Hz threshold
  vals: list[float] = field(default_factory=list)
  frame_vals: list[list[float]] = field(default_factory=list)
  timestamps: deque[int] = field(default_factory=lambda: deque(maxlen=500))
  counter: int = 0
  counter_fail: int = 0
  first_seen_nanos: int = 0
  last_warning_log_nanos: int = 0
  _decode: object = field(default=None, repr=False, compare=False)
  _special: object = field(default=None, repr=False, compare=False)

  def _prepare(self) -> None:
    factory = _decoder_factory
    self._decode = factory(self.signals) if factory is not None else make_python_decoder(self.signals)
    self._special = tuple(
      (i, sig) for i, sig in enumerate(self.signals) if sig.calc_checksum is not None or sig.type == 1
    )

  def rate_limited_log(self, last_update_nanos: int, msg: str) -> None:
    if (last_update_nanos - self.last_warning_log_nanos) >= 1_000_000_000:
      carlog.warning(f"CANParser: {hex(self.address)} {self.name} {msg}")
      self.last_warning_log_nanos = last_update_nanos

  def parse(self, nanos: int, dat: bytes) -> bool:
    if self._decode is None:
      self._prepare()

    checksum_failed = False
    counter_failed = False

    if self.first_seen_nanos == 0:
      self.first_seen_nanos = nanos

    tmp_vals = self._decode(dat)

    for _, sig in self._special:
      if self.ignore_checksum and (self.ignore_counter or sig.type != 1):
        continue
      tmp = get_raw_value(dat, sig)
      if sig.is_signed:
        tmp -= ((tmp >> (sig.size - 1)) & 0x1) * (1 << sig.size)

      if not self.ignore_checksum and sig.calc_checksum is not None:
        expected_checksum = sig.calc_checksum(self.address, sig, bytearray(dat))
        if tmp != expected_checksum:
          checksum_failed = True
          self.log_checksum_failure(nanos, tmp, expected_checksum)

      if not self.ignore_counter and sig.type == 1:
        if not self.update_counter(tmp, sig.size):
          counter_failed = True

    if checksum_failed or counter_failed:
      return False

    if not self.vals:
      self.vals = [0.0] * len(self.signals)

    self.vals[:] = tmp_vals
    self.frame_vals.append(tmp_vals)

    self.timestamps.append(nanos)
    self._learn_frequency()
    return True

  def _learn_frequency(self) -> None:
    if self.frequency < 1e-5 and len(self.timestamps) >= 3:
      dt = (self.timestamps[-1] - self.timestamps[0]) * 1e-9
      if (dt > 1.0 or (self.timestamps.maxlen is not None and len(self.timestamps) >= self.timestamps.maxlen)) and dt != 0:
        self.frequency = min(len(self.timestamps) / dt, 100.0)
        self.timeout_threshold = (1_000_000_000 / self.frequency) * 10

  def log_checksum_failure(self, nanos: int, received: int, expected: int) -> None:
    self.rate_limited_log(nanos, f"checksum failed: received {hex(received)}, calculated {hex(expected)}")

  def update_counter(self, cur_count: int, cnt_size: int) -> bool:
    if ((self.counter + 1) & ((1 << cnt_size) - 1)) != cur_count:
      self.counter_fail = min(self.counter_fail + 1, MAX_BAD_COUNTER)
    elif self.counter_fail > 0:
      self.counter_fail -= 1
    self.counter = cur_count
    return self.counter_fail < MAX_BAD_COUNTER

  def valid(self, current_nanos: int, bus_timeout: bool) -> bool:
    if self.ignore_alive:
      return True
    if not self.timestamps:
      return False
    if (current_nanos - self.timestamps[-1]) > self.timeout_threshold:
      return False
    return True


class FrameValues:
  def __init__(self, state: MessageState):
    self._state = state
    self._index = {sig.name: i for i, sig in enumerate(state.signals)}

  def __getitem__(self, name: str) -> list[float]:
    i = self._index.get(name)
    if i is None:
      return []
    return [vals[i] for vals in self._state.frame_vals]

  def get(self, name: str, default=None):
    return self[name] if name in self._index else default

  def __contains__(self, name: str) -> bool:
    return name in self._index

  def __iter__(self):
    return iter(self._index)

  def __len__(self) -> int:
    return len(self._index)

  def keys(self):
    return self._index.keys()

  def items(self):
    return [(name, self[name]) for name in self._index]

  def values(self):
    return [self[name] for name in self._index]


class VLDict(dict):
  def __init__(self, parser):
    super().__init__()
    self.parser = parser

  def __missing__(self, key):
    self.parser._add_message(key)
    return dict.__getitem__(self, key)


class CANParser:
  def __init__(self, dbc_name: str, messages: list[tuple[str | int, int]], bus: int):
    self.dbc_name: str = dbc_name
    self.bus: int = bus
    self.dbc: DBC = DBC(dbc_name)

    self.vl: dict[int | str, dict[str, float]] = VLDict(self)
    self.vl_all: dict[int | str, dict[str, list[float]]] = {}
    self.ts_nanos: dict[int | str, dict[str, int]] = {}
    self.dat: dict[int | str, bytes] = {}
    self.addresses: set[int] = set()
    self.seen_addresses: set[int] = set()
    self.enable_capture: bool = True
    self.controls_ready: bool = False
    self.message_states: dict[int, MessageState] = {}
    self._fast: dict[int, tuple] = {}
    self._dirty_states: dict[int, MessageState] = {}

    for name_or_addr, freq in messages:
      if isinstance(name_or_addr, numbers.Number):
        msg = self.dbc.addr_to_msg.get(int(name_or_addr))
      else:
        msg = self.dbc.name_to_msg.get(name_or_addr)
      if msg is None:
        raise RuntimeError(f"could not find message {name_or_addr!r} in DBC {dbc_name}")
      if msg.address in self.addresses:
        raise RuntimeError("Duplicate Message Check: %d" % msg.address)

      self._add_message(name_or_addr, freq)

    self.can_invalid_cnt: int = CAN_INVALID_CNT
    self.last_nonempty_nanos: int = 0
    self._last_update_nanos: int = 0

  def _add_message(self, name_or_addr: str | int, freq: int | None = None, ignore_counter: bool = False) -> None:
    if isinstance(name_or_addr, numbers.Number):
      msg = self.dbc.addr_to_msg.get(int(name_or_addr))
    else:
      msg = self.dbc.name_to_msg.get(name_or_addr)
    assert msg is not None
    assert msg.address not in self.addresses

    self.addresses.add(msg.address)
    signal_names = list(msg.sigs.keys())
    signals_dict = {s: 0.0 for s in signal_names}
    dict.__setitem__(self.vl, msg.address, signals_dict)
    dict.__setitem__(self.vl, msg.name, signals_dict)
    self.ts_nanos[msg.address] = {s: 0 for s in signal_names}
    self.ts_nanos[msg.name] = self.ts_nanos[msg.address]
    state = MessageState(
      address=msg.address,
      name=msg.name,
      size=msg.size,
      signals=list(msg.sigs.values()),
      ignore_alive=freq is not None and math.isnan(freq),
      ignore_counter=ignore_counter,
    )
    state.first_seen_nanos = time.monotonic_ns()
    if freq is not None and freq > 0:
      state.frequency = freq
    else:
      # if frequency not specified, assume 1Hz until we learn it
      freq = 1
    state.timeout_threshold = (1_000_000_000 / freq) * 10

    self.message_states[msg.address] = state
    self.vl_all[msg.address] = FrameValues(state)
    self.vl_all[msg.name] = self.vl_all[msg.address]
    self._fast[msg.address] = (signals_dict, self.ts_nanos[msg.address], tuple(sig.name for sig in state.signals))

  @property
  def bus_timeout(self) -> bool:
    ignore_alive = True
    bus_timeout_threshold = 500 * 1_000_000
    for st in self.message_states.values():
      if not st.ignore_alive:
        ignore_alive = False
      if 0 < st.timeout_threshold < bus_timeout_threshold:
        bus_timeout_threshold = st.timeout_threshold
    return ((self._last_update_nanos - self.last_nonempty_nanos) > bus_timeout_threshold) and not ignore_alive

  @property
  def can_valid(self) -> bool:
    valid = True
    counters_valid = True
    bus_timeout = self.bus_timeout
    for state in self.message_states.values():
      if state.counter_fail >= MAX_BAD_COUNTER:
        counters_valid = False
        state.rate_limited_log(self._last_update_nanos, f"counter invalid, {state.counter_fail=} {MAX_BAD_COUNTER=}")
      if not state.valid(self._last_update_nanos, bus_timeout):
        valid = False
        state.rate_limited_log(self._last_update_nanos, "not valid (timeout or missing)")

    # TODO: probably only want to increment this once per update() call
    self.can_invalid_cnt = 0 if valid else min(self.can_invalid_cnt + 1, CAN_INVALID_CNT)
    return self.can_invalid_cnt < CAN_INVALID_CNT and counters_valid

  def update(self, strings, sendcan: bool = False):
    if strings and not isinstance(strings[0], list | tuple):
      strings = [strings]

    dirty = self._dirty_states
    for state in dirty.values():
      state.frame_vals.clear()
    dirty.clear()

    backend = _update_backend
    if backend is not None:
      return backend(self, strings)
    return self._update_python(strings)

  def _update_python(self, strings):
    updated_addrs: set[int] = set()
    bus = self.bus
    capture = self.controls_ready and self.enable_capture
    seen_addresses = self.seen_addresses
    handle_frame = self._handle_frame
    for entry in strings:
      t = entry[0]
      frames = entry[1]
      bus_empty = True
      for address, dat, src in frames:
        if src != bus:
          continue
        bus_empty = False
        if capture:
          seen_addresses.add(address)
        handle_frame(t, address, dat, updated_addrs)

      if not bus_empty:
        self.last_nonempty_nanos = t

      self._last_update_nanos = t

    return updated_addrs

  def _handle_frame(self, t, address, dat, updated_addrs) -> None:
    state = self.message_states.get(address)
    if state is None or len(dat) > 64:
      return
    if state.parse(t, dat):
      updated_addrs.add(address)
      self._dirty_states[address] = state

      vl_addr, ts_addr, names = self._fast[address]
      vl_addr.update(zip(names, state.vals, strict=True))
      ts_addr.update(dict.fromkeys(names, state.timestamps[-1]))
      raw_dat = bytes(dat)
      self.dat[address] = raw_dat
      self.dat[state.name] = raw_dat


class CANDefine:
  def __init__(self, dbc_name: str):
    dbc = DBC(dbc_name)

    dv = defaultdict(dict)
    for val in dbc.vals:
      sgname = val.name
      address = val.address
      msg = dbc.addr_to_msg.get(address)
      if msg is None:
        raise KeyError(address)
      msgname = msg.name
      parts = val.def_val.split()
      values = [int(v) for v in parts[::2]]
      defs = parts[1::2]
      dv[address][sgname] = dict(zip(values, defs, strict=True))
      dv[msgname][sgname] = dv[address][sgname]

    self.dv = dict(dv)
