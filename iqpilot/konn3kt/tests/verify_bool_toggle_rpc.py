#!/usr/bin/env python3
"""Verify Konn3kt bool RPC toggles match on-disk params (run on comma device)."""
from openpilot.common.params import Params
from openpilot.iqpilot.konn3kt.common.params import (
  CELLULAR_UPLOADS_RPC_ALIAS,
  LONGITUDINAL_BACKING_KEYS,
  ONROAD_UPLOADS_KEY,
  get_longitudinal_control_mode_index,
  gsm_metered_from_onroad_uploads,
  onroad_uploads_from_gsm_metered,
)

# App bool RPC keys verified against device params (konn3kt 1.8.65).
BOOL_TOGGLE_KEYS = (
  "AolEnabled",
  "AolMainCruiseAllowed",
  "IQLanePlanner",
  "AlphaLongitudinalEnabled",
)


def _read_param(key: str):
  return Params().get(key)


def _assert_bool(key: str, expected: bool) -> None:
  actual = Params().get_bool(key)
  if actual != expected:
    raise AssertionError(f"{key}: expected {expected}, got {actual}")


def verify_get_bool_params(rpc) -> None:
  keys = list(BOOL_TOGGLE_KEYS)
  keys.extend([CELLULAR_UPLOADS_RPC_ALIAS, ONROAD_UPLOADS_KEY])
  result = rpc.getBoolParams(keys)
  if not isinstance(result, dict):
    raise AssertionError(f"getBoolParams returned {type(result)!r}, expected dict")

  params = Params()
  for key in BOOL_TOGGLE_KEYS:
    if key not in result:
      raise AssertionError(f"getBoolParams missing {key}")
    if bool(result[key]) != params.get_bool(key):
      raise AssertionError(f"getBoolParams[{key}]={result[key]!r}, disk={params.get_bool(key)!r}")

  onroad = params.get_bool(ONROAD_UPLOADS_KEY)
  if ONROAD_UPLOADS_KEY in result and bool(result[ONROAD_UPLOADS_KEY]) != onroad:
    raise AssertionError("getBoolParams OnroadUploads mismatch")
  if CELLULAR_UPLOADS_RPC_ALIAS in result:
    expected_gsm = gsm_metered_from_onroad_uploads(onroad)
    if bool(result[CELLULAR_UPLOADS_RPC_ALIAS]) != expected_gsm:
      raise AssertionError(
        f"getBoolParams GsmMetered={result[CELLULAR_UPLOADS_RPC_ALIAS]!r}, expected {expected_gsm}"
      )


def verify_set_bool_param_roundtrip(rpc) -> None:
  params = Params()
  version_before = int(params.get("ParamsVersion") or 0)

  rpc.setBoolParam(CELLULAR_UPLOADS_RPC_ALIAS, True)
  _assert_bool(ONROAD_UPLOADS_KEY, onroad_uploads_from_gsm_metered(True))
  version_after_uploads = int(params.get("ParamsVersion") or 0)
  if version_after_uploads <= version_before:
    raise AssertionError("ParamsVersion not bumped after GsmMetered write")

  rpc.setBoolParam(CELLULAR_UPLOADS_RPC_ALIAS, False)
  _assert_bool(ONROAD_UPLOADS_KEY, onroad_uploads_from_gsm_metered(False))

  rpc.setBoolParam(ONROAD_UPLOADS_KEY, True)
  _assert_bool(ONROAD_UPLOADS_KEY, True)

  alpha_before = params.get_bool("AlphaLongitudinalEnabled")
  rpc.setBoolParam("AlphaLongitudinalEnabled", not alpha_before)
  mode_index = get_longitudinal_control_mode_index(params)
  stored_mode = int(params.get("LongitudinalControlMode") or -1)
  if stored_mode != mode_index:
    raise AssertionError(
      f"LongitudinalControlMode stale: file={stored_mode}, expected={mode_index}"
    )

  for key in LONGITUDINAL_BACKING_KEYS:
    if key in ("ExperimentalMode", "IQDynamicMode"):
      continue
    rpc.setBoolParam(key, alpha_before)


def main() -> int:
  import openpilot.iqpilot.konn3kt.hephaestus.hephaestusd as wrapper

  rpc = wrapper._private
  verify_get_bool_params(rpc)
  verify_set_bool_param_roundtrip(rpc)
  print("OK: Konn3kt bool toggle RPC matches device params")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
