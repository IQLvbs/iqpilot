#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
import re
import secrets
from pathlib import Path

from iqpilot.common.params import Params
from iqpilot.system.hardware.hw import Paths
from iqpilot.common.swaglog import cloudlog


UNREGISTERED_DONGLE_ID = "UnregisteredDevice"

_DONGLE_ID_RE = re.compile(r"^[a-fA-F0-9]{16}$")
IMEI_WAIT_TIMEOUT = 15.0


def _read_persist_dongle_id() -> str | None:
  p = Path(Paths.persist_root()) / "comma" / "dongle_id"
  try:
    if not p.is_file():
      return None
    s = p.read_text().strip()
    return s or None
  except Exception:
    cloudlog.exception("failed to read persist dongle_id")
    return None


def is_valid_dongle_id(dongle_id: str | None) -> bool:
  return bool(dongle_id and _DONGLE_ID_RE.fullmatch(dongle_id))


def get_cached_dongle_id(params: Params | None = None, prefer_readonly: bool = True) -> str | None:
  ro = _read_persist_dongle_id()
  if is_valid_dongle_id(ro):
    ro = ro.lower()
  if prefer_readonly and ro:
    return ro
  p = Params() if params is None else params
  v = p.get("DongleId")
  if v and v != UNREGISTERED_DONGLE_ID:
    return v.lower() if is_valid_dongle_id(v) else v
  return ro or None


def get_or_create_dongle_id(params: Params | None = None, prefer_readonly: bool = True) -> str:
  p = Params() if params is None else params
  dongle_id = get_cached_dongle_id(p, prefer_readonly=prefer_readonly)
  if dongle_id and dongle_id != UNREGISTERED_DONGLE_ID:
    return dongle_id
  dongle_id = secrets.token_hex(8)
  p.put("DongleId", dongle_id)
  cloudlog.warning(f"generated new DongleId={dongle_id} (no readonly dongle_id found)")
  return dongle_id


_impl = None


def _registration_impl():
  global _impl
  if _impl is None:
    from iqpilot._proprietary_loader import ProprietaryModuleMissing, load_private_module
    try:
      _impl = load_private_module(__name__, "iqpilot_private.konn3kt.registration.reg_core")
    except ProprietaryModuleMissing:
      from konn3kt_private.registration import reg_core as _impl
  return _impl


def ensure_dev_pairing_identity(params: Params | None = None, force_reset: bool = False) -> dict[str, str]:
  return _registration_impl().ensure_dev_pairing_identity(params, force_reset)


def get_registration_identifiers(wait_timeout: float = IMEI_WAIT_TIMEOUT, show_spinner: bool = False) -> tuple[str, str, str]:
  return _registration_impl().get_registration_identifiers(wait_timeout, show_spinner)


def register(show_spinner=False) -> str | None:
  return _registration_impl().register(show_spinner)


if __name__ == "__main__":
  print(register())
