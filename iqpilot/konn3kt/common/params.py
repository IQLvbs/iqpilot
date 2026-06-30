"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos

Konn3kt cloud console gaps (Cellular Uploads / hephaestusd RPC): see iqpilot/konn3kt/KNOWN_ISSUES.md
"""

import base64
import gzip
import json
from cereal import log
from openpilot.common.params import Params, ParamKeyType

PERSONALITY_TO_INT = log.LongitudinalPersonality.schema.enumerants
LONGITUDINAL_CONTROL_MODE_KEY = "LongitudinalControlMode"
LONGITUDINAL_BACKING_KEYS = frozenset({
  "AlphaLongitudinalEnabled",
  "ExperimentalMode",
  "IQDynamicMode",
})
# Konn3kt app maps "Cellular Uploads" to inverted GsmMetered; device uses OnroadUploads.
CELLULAR_UPLOADS_RPC_ALIAS = "GsmMetered"
ONROAD_UPLOADS_KEY = "OnroadUploads"


def onroad_uploads_from_gsm_metered(gsm_metered: bool) -> bool:
  return not gsm_metered


def gsm_metered_from_onroad_uploads(onroad_uploads: bool) -> bool:
  return not onroad_uploads


def get_longitudinal_control_mode_index(params=None) -> int:
  """Derive longitudinal mode index from backing bool params (matches device UI)."""
  params = params or Params()
  if not params.get_bool("AlphaLongitudinalEnabled"):
    return 0  # Stock ACC
  if not params.get_bool("ExperimentalMode"):
    return 1  # IQ.Standard
  return 2 if params.get_bool("IQDynamicMode") else 3  # IQ.Dynamic / IQ.Pilot


def apply_longitudinal_control_mode(index: int, params=None) -> None:
  """Apply longitudinal mode index by updating backing bool params (matches device UI)."""
  params = params or Params()
  previous_alpha = params.get_bool("AlphaLongitudinalEnabled")
  previous_toyota_stock_long = params.get_bool("ToyotaEnforceStockLongitudinal")

  if index == 0:
    params.put_bool("AlphaLongitudinalEnabled", False)
    params.put_bool("ExperimentalMode", False)
    params.put_bool("IQDynamicMode", False)
  elif index == 1:
    params.put_bool("AlphaLongitudinalEnabled", True)
    params.put_bool("ExperimentalMode", False)
    params.put_bool("IQDynamicMode", False)
    params.put("LongitudinalPersonality", PERSONALITY_TO_INT["relaxed"])
  elif index == 2:
    params.put_bool("AlphaLongitudinalEnabled", True)
    params.put_bool("ExperimentalMode", True)
    params.put_bool("IQDynamicMode", True)
  else:
    params.put_bool("AlphaLongitudinalEnabled", True)
    params.put_bool("ExperimentalMode", True)
    params.put_bool("IQDynamicMode", False)

  if index != 0 and previous_toyota_stock_long:
    params.put_bool("ToyotaEnforceStockLongitudinal", False)

  if (
    previous_alpha != params.get_bool("AlphaLongitudinalEnabled") or
    previous_toyota_stock_long != params.get_bool("ToyotaEnforceStockLongitudinal")
  ):
    params.put_bool("OnroadCycleRequested", True)

  sync_longitudinal_control_mode(params)


def sync_longitudinal_control_mode(params=None) -> int:
  """Keep LongitudinalControlMode on disk aligned with backing bool params (Konn3kt wire format)."""
  params = params or Params()
  index = get_longitudinal_control_mode_index(params)
  stored = params.get(LONGITUDINAL_CONTROL_MODE_KEY)
  if stored is None or int(stored) != index:
    params.put(LONGITUDINAL_CONTROL_MODE_KEY, index)
  return index


def param_to_bytes(param_name: str, params=None, get_default=False) -> bytes | None:
  if param_name == LONGITUDINAL_CONTROL_MODE_KEY:
    params = params or Params()
    if get_default:
      return b"0"
    return str(sync_longitudinal_control_mode(params)).encode('utf-8')

  params = params or Params()
  param = params.get(param_name) if not get_default else params.get_default_value(param_name)

  if param is None:
    return None

  param_type = params.get_type(param_name)
  return _encode_param_bytes(param, param_type)


def _encode_param_bytes(param, param_type: ParamKeyType) -> bytes | None:
  if param_type == ParamKeyType.BYTES:
    return bytes(param)
  if param_type == ParamKeyType.JSON:
    return json.dumps(param).encode('utf-8')
  if param_type == ParamKeyType.BOOL:
    # Params.get() returns Python bool; wire format must match on-disk "0"/"1".
    if isinstance(param, bool):
      return b"1" if param else b"0"
    return str(param).encode('utf-8')
  return str(param).encode('utf-8')


def bump_params_version(params=None) -> None:
  """Increment ParamsVersion so Konn3kt can detect local/remote param changes."""
  params = params or Params()
  try:
    current = int(params.get("ParamsVersion") or 0)
    params.put("ParamsVersion", current + 1)
  except Exception:
    pass


def param_from_base64(param_name: str, base64_data: str, is_compressed=False) -> None:
  params = Params()
  value = base64.b64decode(base64_data)

  if is_compressed:
    value = gzip.decompress(value)

  if param_name == LONGITUDINAL_CONTROL_MODE_KEY:
    index = int(value.decode('utf-8'))
    apply_longitudinal_control_mode(index, params)
    bump_params_version(params)
    return

  param_type = params.get_type(param_name)
  param_value = _decode_param_value(value, param_type)
  params.put(param_name, param_value)
  if param_name in LONGITUDINAL_BACKING_KEYS:
    sync_longitudinal_control_mode(params)
  bump_params_version(params)


def save_params_from_base64(params_to_update: dict[str, str], compression: bool = False) -> None:
  """Batch save params from base64 wire values; bumps ParamsVersion once."""
  params = Params()
  for key, value in params_to_update.items():
    raw = base64.b64decode(value)
    if compression:
      raw = gzip.decompress(raw)

    if key == LONGITUDINAL_CONTROL_MODE_KEY:
      apply_longitudinal_control_mode(int(raw.decode('utf-8')), params)
      continue

    param_type = params.get_type(key)
    param_value = _decode_param_value(raw, param_type)
    params.put(key, param_value)
    if key in LONGITUDINAL_BACKING_KEYS:
      sync_longitudinal_control_mode(params)

  bump_params_version(params)


def _decode_param_value(value: bytes, param_type: ParamKeyType) -> bytes | str | int | float | bool | dict | None:
  if param_type != ParamKeyType.BYTES:
    value = value.decode('utf-8')

  if param_type == ParamKeyType.STRING:
    value = value
  elif param_type == ParamKeyType.BOOL:
    value = value.lower() in ('true', '1', 'yes')
  elif param_type == ParamKeyType.INT:
    value = int(value)
  elif param_type == ParamKeyType.FLOAT:
    value = float(value)
  elif param_type == ParamKeyType.TIME:
    value = str(value)
  elif param_type == ParamKeyType.JSON:
    value = json.loads(value)

  return value
