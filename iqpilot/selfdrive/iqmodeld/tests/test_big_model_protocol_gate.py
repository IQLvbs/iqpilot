"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import pytest

from iqpilot.models_private_src import emac_model_meta as emm

CATALOG = {
  emm.DEFAULT_MODEL: {"model_name": emm.BIG_MODEL_NAMES[0], "display_name": "default", "min_protocol": 18},
  "fidx": {"model_name": emm.STATEFUL_MODEL_NAME, "display_name": "fidx", "min_protocol": 21},
  "future": {"model_name": emm.STATEFUL_MODEL_NAME, "display_name": "future", "min_protocol": emm.DEVICE_MAX_PROTOCOL + 1},
}


class _Params:
  def __init__(self, mac: bool, model: str = "fidx"):
    self.mac = mac
    self.model = model

  def get_bool(self, key):
    return key == "IQEmacEnabled" and self.mac

  def get(self, key):
    return self.model if key == "IQEmacModel" else None


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
  monkeypatch.setattr(emm, "load_catalog", lambda params=None: CATALOG)
  monkeypatch.setattr(emm, "refresh_catalog", lambda params=None: None, raising=False)


@pytest.mark.parametrize("mac", [False, True])
def test_fidx_model_is_listed_for_egpu_and_emac(mac):
  listed = dict(emm.big_models(_Params(mac=mac)))
  assert "fidx" in listed
  assert "future" not in listed


def test_mac_runner_resolves_a_fidx_model():
  assert emm.get_model_meta(_Params(mac=True), allow_refresh=True)["key"] == "fidx"


def test_mac_runner_never_resolves_a_model_above_its_protocol():
  assert emm.get_model_meta(_Params(mac=True, model="future"), allow_refresh=True) is None
  assert emm.get_model_meta(_Params(mac=True, model="future"), allow_refresh=False)["key"] == emm.DEFAULT_MODEL
