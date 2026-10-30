import importlib
import random
import sys

import numpy as np
import pytest

from iqdbc.can.dbc import DBC
from iqdbc.can.packer import CANPacker, set_packer_factory
from iqdbc.can.parser import CANParser, make_python_decoder, set_decoder_factory, set_update_backend
from iqdbc.can.tests import ALL_DBCS
from iqdbc.can.tests.reference_packer import CANPacker as ReferencePacker
from iqdbc.can.tests.reference_parser import CANParser as ReferenceParser
from iqdbc.can.tests.test_parser_equivalence import make_frames as parser_frames
from iqdbc.can.tests.test_parser_equivalence import snapshot as parser_snapshot
from iqpilot.cereal import log
from iqpilot.selfdrive.car import native_can
from iqpilot.selfdrive.pandad import pandad_api_impl

DBCS = sorted(ALL_DBCS)


@pytest.fixture(scope='module')
def factory():
  return native_can.make_native_decoder_factory(native_can._load_library())


@pytest.mark.parametrize('dbc_name', DBCS)
def test_native_decoder_matches_the_python_decoder(factory, dbc_name):
  rng = random.Random(dbc_name)
  for msg in DBC(dbc_name).msgs.values():
    signals = list(msg.sigs.values())
    if not signals:
      continue
    native, python = factory(signals), make_python_decoder(signals)
    for _ in range(25):
      length = rng.choice([msg.size, msg.size, max(msg.size - 1, 0), min(msg.size + 2, 64)])
      dat = bytes(rng.getrandbits(8) for _ in range(length))
      assert native(dat) == python(dat)
    assert native(bytes(msg.size)) == python(bytes(msg.size))
    assert native(bytes([255]) * msg.size) == python(bytes([255]) * msg.size)


def test_native_decoder_accepts_buffers_that_are_not_bytes(factory):
  signals = list(DBC('toyota_new_mc_pt_generated').msgs.values())[0].sigs.values()
  decode = factory(list(signals))
  dat = bytearray(range(8))
  assert decode(dat) == decode(bytes(dat))


def test_installed_decoder_leaves_the_parser_output_unchanged():
  checks = [('STEERING_CONTROL', 50)]
  packer = CANPacker('honda_civic_hatchback_ex_2017_can_generated')
  frames = [[0, [packer.make_can_msg('STEERING_CONTROL', 0, {'STEER_TORQUE': 123, 'STEER_TORQUE_REQUEST': 1}, rx_counter=i % 4)]] for i in range(8)]
  try:
    set_decoder_factory(None)
    expected = CANParser('honda_civic_hatchback_ex_2017_can_generated', checks, 0)
    for frame in frames:
      expected.update([frame])
    assert native_can.install()
    actual = CANParser('honda_civic_hatchback_ex_2017_can_generated', checks, 0)
    for frame in frames:
      actual.update([frame])
  finally:
    set_decoder_factory(None)
    set_packer_factory(None)
  assert actual.vl['STEERING_CONTROL'] == expected.vl['STEERING_CONTROL']
  assert actual.vl['STEERING_CONTROL']['STEER_TORQUE'] == 123


def can_event(rng, frames):
  event = log.Event.new_message(valid=True, logMonoTime=rng.getrandbits(63))
  can = event.init('can', len(frames))
  for slot, (address, dat, src) in zip(can, frames, strict=True):
    slot.address, slot.dat, slot.src = address, dat, src
  return event.to_bytes()


def random_frames(rng, count, widths=(0, 1, 3, 8, 12, 16, 20, 24, 32, 48, 64)):
  return [(rng.getrandbits(29), bytes(rng.getrandbits(8) for _ in range(rng.choice(widths))), rng.choice([0, 1, 2, 3, 255]))
          for _ in range(count)]


def legacy_parse(raws):
  previous = pandad_api_impl._native_reader
  pandad_api_impl.set_native_reader(None)
  try:
    return pandad_api_impl.can_capnp_to_list(raws)
  finally:
    pandad_api_impl.set_native_reader(previous)


@pytest.fixture(scope='module')
def reader():
  return native_can.make_can_event_reader(native_can._load_library(), log.Event.schema)


def test_event_reader_matches_the_capnp_reader_including_can_fd_frames(reader):
  rng = random.Random(3)
  raws = [can_event(rng, random_frames(rng, count)) for count in [0, 1, 2, 5, 17, 40, 64, 120] * 6]
  for raw in raws:
    parsed = reader(raw)
    assert parsed is not None
    assert [parsed] == legacy_parse([raw])


def test_event_reader_defers_to_capnp_for_messages_it_cannot_read_in_place(reader):
  rng = random.Random(5)
  oversized = can_event(rng, random_frames(rng, native_can.EVENT_CAPACITY + 1, widths=(8,)))
  assert reader(oversized) is None
  assert pandad_api_impl.can_capnp_to_list([oversized]) == legacy_parse([oversized])
  assert reader(bytearray(b'\x00' * 32)) is None
  assert reader(b'') is None


def test_event_reader_returns_nothing_for_other_event_types(reader):
  other = log.Event.new_message(valid=True, logMonoTime=7)
  other.init('sendcan', 2)
  assert reader(other.to_bytes()) is None


def test_event_reader_survives_corrupted_messages(reader):
  rng = random.Random(9)
  for _ in range(400):
    raw = bytearray(can_event(rng, random_frames(rng, rng.randint(0, 30))))
    for _ in range(rng.randint(1, 6)):
      raw[rng.randrange(len(raw))] = rng.getrandbits(8)
    cut = rng.randint(0, len(raw))
    for candidate in (bytes(raw), bytes(raw[:cut])):
      parsed = reader(candidate)
      if parsed is not None:
        for _, dat, _ in parsed[1]:
          assert len(dat) <= len(candidate)


def test_installed_reader_feeds_can_capnp_to_list():
  rng = random.Random(11)
  raws = [can_event(rng, random_frames(rng, rng.randint(0, 60))) for _ in range(20)]
  expected = legacy_parse(raws)
  try:
    assert native_can.install()
    assert pandad_api_impl.can_capnp_to_list(raws) == expected
  finally:
    pandad_api_impl.set_native_reader(None)
    set_decoder_factory(None)
    set_packer_factory(None)


def packer_values(rng, msg):
  values = {}
  for name, sig in msg.sigs.items():
    if rng.random() < 0.3:
      continue
    span = (1 << min(sig.size, 20)) * abs(sig.factor)
    values[name] = rng.choice([
      rng.uniform(0, span) + sig.offset,
      rng.uniform(-span, span) + sig.offset,
      sig.offset,
      rng.randint(-5, 5),
      rng.random() < 0.5,
      float(np.float64(rng.uniform(0, span))),
    ])
  return values


@pytest.fixture
def native_packer_factory():
  return native_can.make_native_packer_factory(native_can._load_library())


@pytest.mark.parametrize('dbc_name', DBCS)
def test_native_packer_matches_the_python_packer(native_packer_factory, dbc_name):
  rng = random.Random(dbc_name)
  python = ReferencePacker(dbc_name)
  try:
    set_packer_factory(native_packer_factory)
    native = CANPacker(dbc_name)
    messages = [m for m in python.dbc.msgs.values() if m.sigs]
    for msg in rng.sample(messages, min(30, len(messages))):
      for _ in range(6):
        values = packer_values(rng, msg)
        assert native.pack(msg.address, values) == python.pack(msg.address, values)
        assert native.counters == python.counters
  finally:
    set_packer_factory(None)


def test_native_packer_defers_to_python_for_values_it_cannot_pack_exactly(native_packer_factory):
  signals = list(DBC('toyota_new_mc_pt_generated').msgs.values())[0].sigs.values()
  msg = next(m for m in DBC('toyota_new_mc_pt_generated').msgs.values() if m.sigs)
  name = next(iter(msg.sigs))
  python = ReferencePacker('toyota_new_mc_pt_generated')
  try:
    set_packer_factory(native_packer_factory)
    native = CANPacker('toyota_new_mc_pt_generated')
    for bad in (float('nan'), float('inf'), np.float32(1.5), 1e30):
      for packer in (native, python):
        try:
          packer.pack(msg.address, {name: bad})
          outcome = 'ok'
        except (ValueError, OverflowError):
          outcome = 'raises'
        if packer is native:
          native_outcome = outcome
      assert native_outcome == outcome
  finally:
    set_packer_factory(None)
  assert signals


def test_native_crc_matches_the_python_crc():
  from iqdbc.car.volkswagen import mqbcan

  backend = native_can.make_vw_crc_backend(native_can._load_library(), mqbcan.crc_python)
  rng = random.Random(8)
  tables = [None, [], *mqbcan.VOLKSWAGEN_MQB_MEB_CONSTANTS.values(),
            *(entry['magic'] for entry in mqbcan.VOLKSWAGEN_MQB_MEB_GEN2_CONSTANTS.values() if isinstance(entry, dict))]
  for table in tables:
    for _ in range(40):
      length = rng.randint(2, 64)
      dat = bytes(rng.getrandbits(8) for _ in range(length))
      for candidate in (dat, bytearray(dat)):
        assert backend(candidate, table) == mqbcan.crc_python(candidate, table)


def test_native_crc_keeps_python_behavior_for_odd_inputs():
  from iqdbc.car.volkswagen import mqbcan

  backend = native_can.make_vw_crc_backend(native_can._load_library(), mqbcan.crc_python)
  for const in ([1, 2, 3], [300] * 16, [True] * 16):
    dat = bytearray(range(12))
    outcomes = []
    for fn in (backend, mqbcan.crc_python):
      try:
        outcomes.append(fn(dat, const))
      except IndexError:
        outcomes.append('IndexError')
    assert outcomes[0] == outcomes[1]
  with __import__('pytest').raises(IndexError):
    backend(bytearray(b'\x01'), None)


@pytest.fixture
def native_parser_backend():
  module = importlib.import_module(native_can.PARSER_MODULE)
  set_update_backend(native_can.make_parser_backend(module))
  yield
  set_update_backend(None)


@pytest.mark.parametrize('dbc_name', DBCS)
def test_native_parser_update_matches_the_reference_parser(native_parser_backend, dbc_name):
  rng = random.Random(dbc_name)
  packer = CANPacker(dbc_name)
  messages = [m for m in packer.dbc.msgs.values() if m.sigs and m.size <= 64]
  if not messages:
    pytest.skip('no signals')
  wide = [m for m in messages if m.size > 8]
  chosen = rng.sample(wide, min(4, len(wide))) + rng.sample(messages, min(10, len(messages)))
  chosen = list({m.address: m for m in chosen}.values())
  checks = [(m.name, rng.choice([10, 20, 50, 100])) for m in chosen]
  native, reference = CANParser(dbc_name, checks, 0), ReferenceParser(dbc_name, checks, 0)
  native.controls_ready = reference.controls_ready = True
  ignore_flags = rng.random() < 0.3
  if ignore_flags:
    for address in list(native.message_states)[::2]:
      for parser in (native, reference):
        parser.message_states[address].ignore_checksum = True
        parser.message_states[address].ignore_counter = address % 4 == 0

  now = 0
  for _ in range(80):
    now += rng.choice([10_000_000, 10_000_000, 25_000_000])
    entries = [[now, parser_frames(rng, packer, chosen, 0)] for _ in range(rng.randint(1, 3))]
    assert native.update(entries) == reference.update(entries)
    assert parser_snapshot(native) == parser_snapshot(reference)
    assert native.can_valid == reference.can_valid
    assert native.bus_timeout == reference.bus_timeout


def test_native_parser_update_does_not_leak_references(native_parser_backend):
  dbc_name = 'vw_meb'
  packer = CANPacker(dbc_name)
  chosen = [m for m in packer.dbc.msgs.values() if m.sigs and m.size <= 64][:12]
  parser = CANParser(dbc_name, [(m.name, 50) for m in chosen], 0)
  rng = random.Random(1)
  now = 0

  def run(iterations):
    nonlocal now
    for _ in range(iterations):
      now += 10_000_000
      parser.update([[now, parser_frames(rng, packer, chosen, 0)]])
    parser.update([[now + 1, []]])

  run(500)
  state = next(iter(parser.message_states.values()))
  counts = (sys.getrefcount(state), sys.getrefcount(state.vals), sys.getrefcount(state.timestamps), sys.getrefcount(parser.dat))
  blocks = sys.getallocatedblocks()
  run(5000)
  assert (sys.getrefcount(state), sys.getrefcount(state.vals), sys.getrefcount(state.timestamps), sys.getrefcount(parser.dat)) == counts
  assert sys.getallocatedblocks() - blocks < 4000
