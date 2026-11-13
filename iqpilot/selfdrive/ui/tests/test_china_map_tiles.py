# Copyright (c) 2026 IQ.Lvbs. All rights reserved.
import math
from types import SimpleNamespace

import pytest

from iqpilot.ui.onroad import map_datum
from iqpilot.ui.onroad import nav_map_panel as nav
from iqpilot.ui.onroad import nav_map_utils as utils


class _Client:
  def in_mainland_china(self, lat, lon):
    return 73.0 <= lon <= 135.0 and 18.0 <= lat <= 54.0

  def wgs84_to_gcj02(self, lat, lon):
    return SimpleNamespace(latitude=lat + 0.0012, longitude=lon + 0.0049)


@pytest.fixture(autouse=True)
def _client(monkeypatch):
  monkeypatch.setattr(map_datum, "_client", _Client())
  map_datum.reset()
  yield
  map_datum.reset()


def test_the_view_shifts_to_the_chinese_datum_only_inside_mainland_china():
  assert map_datum.update(31.5, 120.3)
  assert map_datum.shift(31.5, 120.3) == pytest.approx((31.5012, 120.3049))
  assert not map_datum.update(48.85, 2.35)
  assert map_datum.shift(48.85, 2.35) == (48.85, 2.35)


def test_without_the_private_client_nothing_is_shifted(monkeypatch):
  monkeypatch.setattr(map_datum, "_client", None)
  assert not map_datum.update(31.5, 120.3)
  assert map_datum.shift(31.5, 120.3) == (31.5, 120.3)


def test_the_projection_moves_with_the_shift():
  map_datum.reset()
  plain = utils.mercator_world_px(31.5, 120.3, 17)
  map_datum.update(31.5, 120.3)
  shifted = utils.mercator_world_px(31.5, 120.3, 17)
  east_m = (shifted[0] - plain[0]) / (256 * 2 ** 17) * 360 * 111320 * math.cos(math.radians(31.5))
  assert east_m == pytest.approx(0.0049 * 111320 * math.cos(math.radians(31.5)), rel=0.02)
  assert shifted[1] < plain[1]


def test_amap_tiles_are_requested_unkeyed_from_a_spread_of_servers():
  url0, params = nav.build_amap_tile_url(17, 107000, 52000)
  url1, _ = nav.build_amap_tile_url(17, 107001, 52000)
  assert url0 != url1 and "autonavi.com/appmaptile" in url0
  assert params == {"x": 107000, "y": 52000, "z": 17, "lang": "zh_cn", "size": 1, "scl": 2, "style": 7}


def test_amap_tiles_never_ask_for_a_zoom_above_18(tmp_path, monkeypatch):
  monkeypatch.setattr(nav, "TILE_CACHE_ROOT", tmp_path)
  provider = nav.AmapTileProvider()
  z, scale, *_ = provider._visible_tile_keys(31.5, 120.3, 20.0, 400, 300)
  assert z == 18 and scale == pytest.approx(4.0)
  assert provider._token() == "amap"
  assert "amap" in provider._cache_path((18, 1, 2)).parts


def test_the_online_provider_follows_the_country(tmp_path, monkeypatch):
  monkeypatch.setattr(nav, "TILE_CACHE_ROOT", tmp_path)
  provider = nav.OnlineTileProvider()
  provider._select(48.85, 2.35)
  assert provider._active is provider._mapbox
  provider._select(31.5, 120.3)
  assert provider._active is provider._amap and map_datum.active()
  provider._select(48.85, 2.35)
  assert provider._active is provider._mapbox and not map_datum.active()
