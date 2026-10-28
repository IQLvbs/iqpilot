# Copyright (c) 2026 IQ.Lvbs. All rights reserved.


def write_setup_claim(ble):
  if ble is None or not getattr(ble, "phone_active", False):
    return
  try:
    import hashlib
    claim_id = hashlib.sha256(f"k3setup-claim:v1:{ble.code}:{ble.serial}".encode()).hexdigest()
    with open("/data/setup_claim_id", "w") as f:
      f.write(claim_id)
  except Exception:
    pass


def maybe_update_os(install_path: str, hardware, ble, download_failed, label: str) -> bool:
  # The freshly-installed fork pins the IQ.OS it needs in launch_env.sh. If it
  # differs from what we're running, flash it now (via comma's agnos.py) so the
  # upcoming single reboot lands on a compatible OS instead of dead-ending on
  # "update required". Returns False (and shows Download Failed) on abort.
  from iqpilot.system.ui.lib.os_update import os_update_needed, run_agnos_update
  try:
    needed, current, required = os_update_needed(install_path)
  except Exception:
    return True  # never block an install on a version-check failure
  if not needed:
    return True

  # When a phone is driving setup, require it to confirm the OS update. With no
  # phone (on-screen-only install) proceed automatically — the fork requires it.
  if ble is not None and getattr(ble, "phone_active", False):
    ble.os_update.request(current, required)
    ble.set_install_progress("os_update_required", 0, os_from=current, os_to=required)
    if not ble.os_update.wait_for_confirm(timeout=300):
      ble.set_install_progress("failed", error="os_update_not_confirmed")
      download_failed(label, f"IQ.OS update to {required} was not confirmed.")
      return False

  def _cb(pct: int, note: str):
    if ble is not None:
      ble.set_install_progress("os_updating", pct, error=note, os_from=current, os_to=required)

  if not run_agnos_update(install_path, hardware.get_device_type(), _cb):
    if ble is not None:
      ble.set_install_progress("failed", error="os_update_failed")
    download_failed(label, f"IQ.OS update to {required} failed. Please try again.")
    return False
  return True
