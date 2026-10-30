import pytest

from iqdbc.car import cached_params
from iqdbc.car.cached_params import CachedParams, PARAMS_REFRESH_S


class FakeParams:
  def __init__(self):
    self.values = {"A": True, "B": False}
    self.reads = []

  def get_bool(self, key, block=False):
    self.reads.append(key)
    if key not in self.values:
      raise KeyError(key)
    return self.values[key]

  def put_bool(self, key, value):
    self.values[key] = value

  def get(self, key):
    return "raw"


@pytest.fixture
def clock(monkeypatch):
  now = [100.0]

  class Time:
    @staticmethod
    def monotonic():
      return now[0]

  monkeypatch.setattr(cached_params, "time", Time)
  return now


def test_reads_once_within_the_refresh_window(clock):
  fake = FakeParams()
  params = CachedParams(fake)
  assert params.get_bool("A") is True
  clock[0] += PARAMS_REFRESH_S / 2
  fake.values["A"] = False
  assert params.get_bool("A") is True
  assert fake.reads == ["A"]


def test_rereads_after_the_refresh_window(clock):
  fake = FakeParams()
  params = CachedParams(fake)
  assert params.get_bool("A") is True
  clock[0] += PARAMS_REFRESH_S * 2
  fake.values["A"] = False
  assert params.get_bool("A") is False
  assert fake.reads == ["A", "A"]


def test_keys_are_cached_independently(clock):
  fake = FakeParams()
  params = CachedParams(fake)
  assert params.get_bool("A") is True
  assert params.get_bool("B") is False
  assert params.get_bool("A") is True
  assert params.get_bool("B") is False
  assert fake.reads == ["A", "B"]


def test_a_write_through_the_wrapper_is_seen_immediately(clock):
  fake = FakeParams()
  params = CachedParams(fake)
  assert params.get_bool("A") is True
  params.put_bool("A", False)
  assert params.get_bool("A") is False


def test_extra_arguments_bypass_the_cache(clock):
  fake = FakeParams()
  params = CachedParams(fake)
  params.get_bool("A", block=True)
  params.get_bool("A", block=True)
  assert fake.reads == ["A", "A"]


def test_errors_are_not_cached(clock):
  fake = FakeParams()
  params = CachedParams(fake)
  with pytest.raises(KeyError):
    params.get_bool("missing")
  fake.values["missing"] = True
  assert params.get_bool("missing") is True


def test_other_attributes_pass_through(clock):
  assert CachedParams(FakeParams()).get("A") == "raw"
