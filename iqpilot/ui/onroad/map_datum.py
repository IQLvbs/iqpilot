from __future__ import annotations


def _load_client():
  try:
    from iqpilot.system.proprietary_runtime._verified_import import import_verified_module
    return import_verified_module("iqpilot_navd_private", "iqpilot_private.navd.amap_client")
  except Exception:
    return None


_client = _load_client()
_offset: tuple[float, float] | None = None
_cell: tuple[int, int] | None = None


def in_china(latitude: float, longitude: float) -> bool:
  return _client is not None and bool(_client.in_mainland_china(latitude, longitude))


def update(latitude: float, longitude: float) -> bool:
  global _offset, _cell
  cell = (round(latitude * 1000), round(longitude * 1000))
  if cell == _cell:
    return _offset is not None
  _cell = cell
  _offset = None
  if in_china(latitude, longitude):
    shifted = _client.wgs84_to_gcj02(latitude, longitude)
    _offset = (shifted.latitude - latitude, shifted.longitude - longitude)
  return _offset is not None


def active() -> bool:
  return _offset is not None


def shift(latitude: float, longitude: float) -> tuple[float, float]:
  if _offset is None:
    return latitude, longitude
  return latitude + _offset[0], longitude + _offset[1]


def reset() -> None:
  global _offset, _cell
  _offset = None
  _cell = None
