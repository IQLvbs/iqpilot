"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
from iqpilot.selfdrive.ui.mici.layouts.settings.network.wifi_persistence import NetworkPersistenceFilter


class Clock:
  def __init__(self):
    self.now = 100.0

  def __call__(self) -> float:
    return self.now

  def advance(self, seconds: float):
    self.now += seconds


def _filter() -> tuple[NetworkPersistenceFilter, Clock]:
  clock = Clock()
  return NetworkPersistenceFilter(clock=clock), clock


def test_single_sighting_is_not_persistent():
  flt, _ = _filter()
  flt.observe(["passing-car"])
  assert not flt.is_persistent("passing-car")


def test_two_scans_five_seconds_apart_is_persistent():
  flt, clock = _filter()
  flt.observe(["hotspot"])
  clock.advance(5.0)
  flt.observe(["hotspot"])
  assert flt.is_persistent("hotspot")


def test_back_to_back_updates_do_not_count_as_persistence():
  flt, clock = _filter()
  flt.observe(["burst"])
  clock.advance(0.2)
  flt.observe(["burst"])
  clock.advance(0.2)
  flt.observe(["burst"])
  assert not flt.is_persistent("burst")


def test_network_that_drops_out_restarts_its_clock():
  flt, clock = _filter()
  flt.observe(["flaky"])
  clock.advance(3.0)
  flt.observe([])
  clock.advance(3.0)
  flt.observe(["flaky"])
  clock.advance(3.0)
  flt.observe(["flaky"])
  assert not flt.is_persistent("flaky")
  clock.advance(2.0)
  flt.observe(["flaky"])
  assert flt.is_persistent("flaky")


def test_persistent_network_stays_persistent_after_leaving_range():
  flt, clock = _filter()
  flt.observe(["home"])
  clock.advance(5.0)
  flt.observe(["home"])
  clock.advance(5.0)
  flt.observe([])
  assert flt.is_persistent("home")


def test_reset_sightings_discards_stale_progress_but_keeps_persistent():
  flt, clock = _filter()
  flt.observe(["stale", "home"])
  clock.advance(5.0)
  flt.observe(["home"])
  flt.observe(["home"])
  flt.reset_sightings()
  clock.advance(60.0)
  flt.observe(["stale"])
  assert not flt.is_persistent("stale")
  assert flt.is_persistent("home")
