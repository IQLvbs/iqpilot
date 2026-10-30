import random

import pytest

from iqdbc.can.packer import CANPacker
from iqdbc.can.parser import CANParser
from iqdbc.can.tests import ALL_DBCS
from iqdbc.can.tests.reference_parser import CANParser as ReferenceParser

MESSAGES_PER_DBC = 10
UPDATES = 60
DBCS = sorted(ALL_DBCS)


def snapshot(parser):
  states = {
    address: (
      state.vals, state.counter, state.counter_fail, state.frequency, state.timeout_threshold,
      list(state.timestamps),
    )
    for address, state in parser.message_states.items()
  }
  vl_all = {key: {name: list(values) for name, values in per_message.items()} for key, per_message in parser.vl_all.items()}
  return {
    'vl': {key: dict(values) for key, values in parser.vl.items()},
    'vl_all': {key: {name: values for name, values in per_message.items() if values} for key, per_message in vl_all.items()},
    'ts_nanos': {key: dict(values) for key, values in parser.ts_nanos.items()},
    'dat': dict(parser.dat),
    'states': states,
    'seen_addresses': set(parser.seen_addresses),
    'last_nonempty_nanos': parser.last_nonempty_nanos,
    'last_update_nanos': parser._last_update_nanos,
  }


def make_frames(rng, packer, messages, bus):
  frames = []
  for _ in range(rng.randint(1, 6)):
    msg = rng.choice(messages)
    src = bus if rng.random() < 0.85 else bus + 1
    if rng.random() < 0.5:
      values = {name: rng.uniform(0, 3) * sig.factor + sig.offset for name, sig in msg.sigs.items() if rng.random() < 0.7}
      packed = packer.make_can_msg(msg.address, src, values)
      if packed[1]:
        frames.append((packed[0], bytes(packed[1]), packed[2]))
        continue
    size = rng.choice([msg.size, msg.size, max(msg.size - 1, 1), min(msg.size + 1, 64), 65])
    frames.append((msg.address, bytes(rng.getrandbits(8) for _ in range(size)), src))
  return frames


@pytest.mark.parametrize('dbc_name', DBCS)
def test_parser_matches_the_reference_parser(dbc_name):
  rng = random.Random(dbc_name)
  packer = CANPacker(dbc_name)
  messages = [m for m in packer.dbc.msgs.values() if m.sigs and m.size <= 64]
  if not messages:
    pytest.skip('no signals')
  wide = [m for m in messages if m.size > 8]
  chosen = rng.sample(wide, min(4, len(wide))) + rng.sample(messages, min(MESSAGES_PER_DBC, len(messages)))
  chosen = list({m.address: m for m in chosen}.values())
  checks = [(m.name, rng.choice([10, 20, 50, 100])) for m in chosen]
  new, reference = CANParser(dbc_name, checks, 0), ReferenceParser(dbc_name, checks, 0)
  new.controls_ready = reference.controls_ready = True

  now = 0
  for _ in range(UPDATES):
    now += rng.choice([10_000_000, 10_000_000, 25_000_000])
    entries = [[now, make_frames(rng, packer, chosen, 0)] for _ in range(rng.randint(1, 3))]
    assert new.update(entries) == reference.update(entries)
    assert snapshot(new) == snapshot(reference)
    assert new.can_valid == reference.can_valid
    assert new.bus_timeout == reference.bus_timeout
