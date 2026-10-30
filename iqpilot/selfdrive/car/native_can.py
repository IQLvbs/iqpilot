import ctypes
import importlib
import struct
from array import array
from pathlib import Path

from iqpilot.common.swaglog import cloudlog

LIBRARY_PATH = Path(__file__).with_name('libcansignals.so')


class _Signal(ctypes.Structure):
  _fields_ = [
    ('msb', ctypes.c_int32),
    ('lsb', ctypes.c_int32),
    ('size', ctypes.c_int32),
    ('is_signed', ctypes.c_int32),
    ('is_little_endian', ctypes.c_int32),
    ('pad', ctypes.c_int32),
    ('factor', ctypes.c_double),
    ('offset', ctypes.c_double),
  ]


EVENT_CAPACITY = 1024


class _EventLayout(ctypes.Structure):
  _fields_ = [
    ('union_byte_offset', ctypes.c_int32),
    ('can_tag', ctypes.c_int32),
    ('can_pointer_index', ctypes.c_int32),
    ('mono_byte_offset', ctypes.c_int32),
    ('address_byte_offset', ctypes.c_int32),
    ('src_byte_offset', ctypes.c_int32),
    ('dat_pointer_index', ctypes.c_int32),
    ('pad', ctypes.c_int32),
  ]


def _load_library():
  lib = ctypes.CDLL(str(LIBRARY_PATH))
  lib.can_signals_decode.restype = None
  lib.can_signals_decode.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
  lib.can_vw_mqb_meb_crc.restype = ctypes.c_int
  lib.can_vw_mqb_meb_crc.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p]
  lib.can_signals_pack.restype = ctypes.c_int
  lib.can_signals_pack.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
  ]
  lib.can_event_parse.restype = ctypes.c_int
  lib.can_event_parse.argtypes = [
    ctypes.c_char_p, ctypes.c_int64, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32,
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
  ]
  return lib


def make_native_packer_factory(lib):
  pack_signals = lib.can_signals_pack

  def factory(signals):
    count = len(signals)
    table = (_Signal * count)(*(
      _Signal(sig.msb, sig.lsb, sig.size, int(sig.is_signed), int(sig.is_little_endian), 0, sig.factor, sig.offset)
      for sig in signals
    ))
    table_address = ctypes.addressof(table)

    def pack(dat, indices, values):
      for value in values:
        kind = value.__class__
        if kind is not float and kind is not int and kind is not bool and not isinstance(value, float):
          return False
      if not indices:
        return True
      index_buffer = array('i', indices)
      value_buffer = array('d', values)
      view = (ctypes.c_char * len(dat)).from_buffer(dat)
      return pack_signals(table_address, count, index_buffer.buffer_info()[0], value_buffer.buffer_info()[0],
                          len(indices), ctypes.addressof(view), len(dat)) == 0

    pack.keepalive = table
    return pack

  return factory


def make_vw_crc_backend(lib, python_backend):
  crc = lib.can_vw_mqb_meb_crc
  tables = {}

  def backend(d, const):
    if len(d) < 2:
      return python_backend(d, const)
    if d.__class__ is not bytes:
      d = bytes(d)
    if not const:
      return crc(d, len(d), None)
    key = tuple(const)
    table = tables.get(key)
    if table is None:
      if len(key) != 16 or any(v.__class__ is not int or not 0 <= v <= 255 for v in key):
        return python_backend(d, const)
      table = tables[key] = bytes(key)
    return crc(d, len(d), table)

  return backend


PARSER_MODULE = 'iqpilot.selfdrive.car._can_parser_native'
MAX_NATIVE_SIGNALS = 256
KIND_PYTHON, KIND_MQB_MEB, KIND_GEN2, KIND_XOR = 0, 1, 2, 3


def _constants_table(values):
  if not values:
    return None
  if len(values) != 16 or any(v.__class__ is not int or not 0 <= v <= 255 for v in values):
    return False
  return bytes(values)


def _checksum_config(mqbcan, address, kind):
  default = _constants_table(mqbcan.VOLKSWAGEN_MQB_MEB_CONSTANTS.get(address))
  if default is False:
    return None
  has_gen2, gen2_length, gen2_magic = 0, 0, bytes(16)
  if kind == KIND_GEN2:
    entry = mqbcan.VOLKSWAGEN_MQB_MEB_GEN2_CONSTANTS.get(address)
    if entry:
      magic = _constants_table(entry['magic'])
      if not magic or entry['length'].__class__ is not int or entry['length'] < 0:
        return None
      has_gen2, gen2_length, gen2_magic = 1, entry['length'], magic
  return struct.pack('<4i16s16s', int(default is not None), has_gen2, gen2_length, 0, default or bytes(16), gen2_magic)


def _build_slot(parser, address, state, mqbcan):
  signals = state.signals
  if len(signals) > MAX_NATIVE_SIGNALS:
    return None
  plan = b''.join(struct.pack('<6i2d', sig.msb, sig.lsb, sig.size, int(sig.is_signed), int(sig.is_little_endian), 0,
                              sig.factor, sig.offset) for sig in signals)
  entries = []
  for index, sig in enumerate(signals):
    if sig.calc_checksum is None and sig.type != 1:
      continue
    if sig.is_signed or sig.size > 64:
      return None
    kind = KIND_PYTHON
    if mqbcan is not None and sig.calc_checksum is not None:
      if sig.calc_checksum is mqbcan.volkswagen_mqb_meb_checksum:
        kind = KIND_MQB_MEB
      elif sig.calc_checksum is mqbcan.volkswagen_mqb_meb_gen2_checksum:
        kind = KIND_GEN2
      elif sig.calc_checksum is mqbcan.xor_checksum:
        kind = KIND_XOR
    entries.append((index, sig, kind))

  table_kinds = {kind for _, _, kind in entries if kind in (KIND_MQB_MEB, KIND_GEN2)}
  config = struct.pack('<4i16s16s', 0, 0, 0, 0, bytes(16), bytes(16))
  if table_kinds:
    built = _checksum_config(mqbcan, address, KIND_GEN2 if KIND_GEN2 in table_kinds else KIND_MQB_MEB)
    if built is None:
      entries = [(i, s, KIND_PYTHON if k in (KIND_MQB_MEB, KIND_GEN2) else k) for i, s, k in entries]
    else:
      config = built

  specials = b''.join(struct.pack('<8i', index, sig.size, int(sig.type == 1), int(sig.calc_checksum is not None), kind,
                                  sig.start_bit // 8, 0, 0) for index, sig, kind in entries)
  sigs = tuple(sig for _, sig, _ in entries)
  callbacks = tuple(sig.calc_checksum for _, sig, _ in entries)
  vl, ts, names = parser._fast[address]
  return (state, vl, ts, names, state.name, plan, len(signals), specials, len(entries), config, state.address,
          sigs, callbacks, state.log_checksum_failure, state._learn_frequency)


def make_parser_backend(module):
  try:
    from iqdbc.car.volkswagen import mqbcan
  except ImportError:
    mqbcan = None
  update = module.update

  class Context:
    __slots__ = ('count', 'slots')

  def build(parser):
    context = Context()
    context.count = len(parser.message_states)
    context.slots = {address: _build_slot(parser, address, state, mqbcan) for address, state in parser.message_states.items()}
    return context

  def backend(parser, strings):
    context = parser.__dict__.get('_native_context')
    if context is None or context.count != len(parser.message_states):
      context = parser.__dict__['_native_context'] = build(parser)
    times = [None, None]
    try:
      return update(context.slots, strings, parser.bus, bool(parser.controls_ready and parser.enable_capture),
                    parser.seen_addresses, parser._dirty_states, parser.dat, set(), times, parser._handle_frame)
    finally:
      if times[0] is not None:
        parser.last_nonempty_nanos = times[0]
      if times[1] is not None:
        parser._last_update_nanos = times[1]

  return backend


def make_can_event_reader(lib, event_schema):
  fields = event_schema.fields
  element = fields['can'].schema.elementType.fields
  layout = _EventLayout(
    event_schema.node.struct.discriminantOffset * 2,
    fields['can'].proto.discriminantValue,
    fields['can'].proto.slot.offset,
    fields['logMonoTime'].proto.slot.offset * 8,
    element['address'].proto.slot.offset * 4,
    element['src'].proto.slot.offset,
    element['dat'].proto.slot.offset,
    0,
  )
  mono = ctypes.c_uint64()
  addr = (ctypes.c_uint32 * EVENT_CAPACITY)()
  off = (ctypes.c_uint32 * EVENT_CAPACITY)()
  length = (ctypes.c_uint32 * EVENT_CAPACITY)()
  src = (ctypes.c_uint32 * EVENT_CAPACITY)()
  parse = lib.can_event_parse
  layout_address = ctypes.addressof(layout)
  mono_address = ctypes.addressof(mono)
  addr_address, off_address = ctypes.addressof(addr), ctypes.addressof(off)
  length_address, src_address = ctypes.addressof(length), ctypes.addressof(src)

  def read(raw):
    if raw.__class__ is not bytes:
      return None
    count = parse(raw, len(raw), layout_address, mono_address, EVENT_CAPACITY,
                  addr_address, off_address, length_address, src_address)
    if count < 0:
      return None
    return mono.value, [(a, raw[o:o + n], s) for a, o, n, s in zip(addr[:count], off[:count], length[:count], src[:count], strict=True)]

  read.keepalive = layout
  return read


def make_native_decoder_factory(lib):
  decode_signals = lib.can_signals_decode

  def factory(signals):
    count = len(signals)
    table = (_Signal * count)(*(
      _Signal(sig.msb, sig.lsb, sig.size, int(sig.is_signed), int(sig.is_little_endian), 0, sig.factor, sig.offset)
      for sig in signals
    ))
    out = (ctypes.c_double * count)()
    table_address = ctypes.addressof(table)
    out_address = ctypes.addressof(out)

    def decode(dat):
      if dat.__class__ is not bytes:
        dat = bytes(dat)
      decode_signals(table_address, count, dat, len(dat), out_address)
      return out[:]

    decode.keepalive = (table, out)
    return decode

  return factory


def install() -> bool:
  try:
    lib = _load_library()
  except OSError:
    cloudlog.warning("native CAN library unavailable, using the Python CAN paths")
    return False

  from iqpilot.cereal import log
  from iqpilot.selfdrive.pandad import pandad_api_impl
  pandad_api_impl.set_native_reader(make_can_event_reader(lib, log.Event.schema))

  try:
    from iqdbc.can.parser import set_decoder_factory
  except ImportError:
    cloudlog.warning("iqdbc has no pluggable CAN decoder, using the Python decoder")
    return False
  set_decoder_factory(make_native_decoder_factory(lib))

  try:
    from iqdbc.can.packer import set_packer_factory
  except ImportError:
    cloudlog.warning("iqdbc has no pluggable CAN packer, using the Python packer")
    return True
  set_packer_factory(make_native_packer_factory(lib))

  try:
    from iqdbc.car.volkswagen import mqbcan
  except ImportError:
    return True
  if hasattr(mqbcan, 'set_crc_backend'):
    mqbcan.set_crc_backend(make_vw_crc_backend(lib, mqbcan.crc_python))

  try:
    from iqdbc.can.parser import set_update_backend
    set_update_backend(make_parser_backend(importlib.import_module(PARSER_MODULE)))
  except (ImportError, AttributeError):
    cloudlog.warning("native CAN parser update unavailable, using the Python update")
  return True
