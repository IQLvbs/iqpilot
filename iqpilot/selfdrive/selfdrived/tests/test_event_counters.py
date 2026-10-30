import random
from bisect import insort

from iqpilot.selfdrive.selfdrived.events import Events


class ReferenceEvents(Events):
  def clear(self):
    refreshed = {}
    for event_name, frames_seen in self.event_counters.items():
      refreshed[event_name] = frames_seen + 1 if event_name in self._live_names else 0
    self.event_counters = refreshed
    self._live_names = list(self._latched_names)

  def remove(self, event_name, static=False):
    if static and event_name in self._latched_names:
      self._latched_names.remove(event_name)
    if event_name in self._live_names:
      self.event_counters[event_name] = self.event_counters.get(event_name, 0) + 1
      self._live_names.remove(event_name)

  def add(self, event_name, static=False):
    if static:
      insort(self._latched_names, event_name)
    insort(self._live_names, event_name)


def test_counters_match_the_full_scan_implementation():
  rng = random.Random(1)
  current, reference = Events(), ReferenceEvents()
  names = sorted(current.event_counters)[:24]
  for _ in range(4000):
    operation = rng.random()
    name = rng.choice(names + [10_000])
    static = rng.random() < 0.1
    if operation < 0.45:
      current.add(name, static=static)
      reference.add(name, static=static)
    elif operation < 0.6:
      current.remove(name, static=static)
      reference.remove(name, static=static)
    else:
      current.clear()
      reference.clear()
    assert current.event_counters == reference.event_counters
    assert current.events == reference.events


def test_assigned_counters_are_cleared_when_their_event_is_gone():
  events = Events()
  name = sorted(events.event_counters)[0]
  events.event_counters = {name: 7}
  events.clear()
  assert events.event_counters == {name: 0}
  events.add(name)
  events.clear()
  events.add(name)
  events.clear()
  assert events.event_counters == {name: 2}
