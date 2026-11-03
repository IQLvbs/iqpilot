"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from types import SimpleNamespace

import pytest

from iqdbc.car import car_helpers
from iqdbc.car.vin import VIN_UNKNOWN


@pytest.fixture
def queries(monkeypatch):
  calls = []

  def fake_get_vin(*args, **kwargs):
    calls.append("vin")
    return 0, 0, VIN_UNKNOWN

  monkeypatch.setattr(car_helpers, "get_vin", fake_get_vin)
  monkeypatch.setattr(car_helpers, "get_present_ecus", lambda *args, **kwargs: set())
  monkeypatch.setattr(car_helpers, "get_fw_versions_ordered", lambda *args, **kwargs: [])
  monkeypatch.setattr(car_helpers, "match_fw_to_car", lambda *args, **kwargs: (True, set()))
  monkeypatch.setattr(car_helpers, "can_fingerprint", lambda can_recv: (None, {}))
  return calls


def run_fingerprint(cached_vin):
  cached = SimpleNamespace(brand="honda", carFw=[object()], carVin=cached_vin)
  car_helpers.fingerprint(lambda *args, **kwargs: [], lambda *args, **kwargs: None, lambda *args, **kwargs: None, 1, cached, None)


def test_cached_params_with_unknown_vin_requeries(queries):
  run_fingerprint("".join(["0"] * 17))
  assert queries == ["vin"]


def test_cached_params_with_known_vin_skip_the_query(queries):
  run_fingerprint("1HGCV1F30LA000001")
  assert queries == []
