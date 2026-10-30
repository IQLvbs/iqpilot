import random

import pytest

from iqdbc.can.packer import CANPacker
from iqdbc.can.tests import ALL_DBCS
from iqdbc.can.tests.reference_packer import CANPacker as ReferencePacker

DBCS = sorted(ALL_DBCS)


def random_values(rng, msg):
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
    ])
  if rng.random() < 0.1:
    values['NOT_A_SIGNAL'] = 1.0
  return values


@pytest.mark.parametrize('dbc_name', DBCS)
def test_packer_matches_the_reference_packer(dbc_name):
  rng = random.Random(dbc_name)
  new, reference = CANPacker(dbc_name), ReferencePacker(dbc_name)
  messages = [m for m in new.dbc.msgs.values() if m.sigs]
  for msg in rng.sample(messages, min(40, len(messages))):
    for _ in range(6):
      values = random_values(rng, msg)
      assert new.pack(msg.address, values) == reference.pack(msg.address, values)
      assert new.counters == reference.counters
  assert new.pack(0xFFFFFFF, {}) == reference.pack(0xFFFFFFF, {})
