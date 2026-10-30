# Copyright (c) 2026 IQ.Lvbs. All rights reserved.
import hashlib
from types import SimpleNamespace

import pytest

from iqpilot.system.ui.lib import os_update, setup_install


@pytest.mark.parametrize("device,manifest", [("tici", "agnos_tici_15_1.json"), ("tizi", "agnos.json"), ("mici", "agnos.json")])
@pytest.mark.parametrize("phone,confirmed,success", [(False, False, True), (True, False, True), (True, True, True), (True, True, False)])
def test_update_confirmation_and_device_manifest(monkeypatch, mocker, device, manifest, phone, confirmed, success):
  events = []
  coordinator = SimpleNamespace(request=lambda *args: events.append("request"),
                                wait_for_confirm=lambda timeout: events.append(("confirm", timeout)) or confirmed)
  ble = SimpleNamespace(phone_active=phone, os_update=coordinator,
                        set_install_progress=lambda state, *args, **kwargs: events.append(state))
  hardware = SimpleNamespace(get_device_type=lambda: device)
  monkeypatch.setattr(os_update, "os_update_needed", lambda path: (True, "old", "new"))

  def flash(path, device_type, callback):
    assert os_update.agnos_manifest_path(path, device_type).endswith("/" + manifest)
    events.append("flash")
    callback(50, "flashing")
    return success

  monkeypatch.setattr(os_update, "run_agnos_update", flash)
  failed = mocker.Mock()
  assert setup_install.maybe_update_os("/checkout", hardware, ble, failed, "release") == (success and (not phone or confirmed))
  if phone and not confirmed:
    assert events == ["request", "os_update_required", ("confirm", 300), "failed"]
    failed.assert_called_once_with("release", "IQ.OS update to new was not confirmed.")
  else:
    assert "flash" in events
    if phone:
      assert events.index(("confirm", 300)) < events.index("flash")
    assert failed.call_count == int(not success)


@pytest.mark.parametrize("result", [(False, "same", "same"), RuntimeError("unavailable")])
def test_version_check_does_not_block_install(monkeypatch, mocker, result):
  monkeypatch.setattr(os_update, "os_update_needed", mocker.Mock(side_effect=result if isinstance(result, Exception) else None, return_value=result))
  flash = mocker.Mock()
  monkeypatch.setattr(os_update, "run_agnos_update", flash)
  assert setup_install.maybe_update_os("/checkout", None, None, mocker.Mock(), "release")
  flash.assert_not_called()


@pytest.mark.parametrize("active", [False, True])
def test_setup_claim_requires_active_phone(monkeypatch, mocker, active):
  opened = mocker.mock_open()
  monkeypatch.setattr("builtins.open", opened)
  setup_install.write_setup_claim(SimpleNamespace(phone_active=active, code="123456", serial="test-device"))
  if active:
    opened.assert_called_once_with("/data/setup_claim_id", "w")
    opened().write.assert_called_once_with(hashlib.sha256(b"k3setup-claim:v1:123456:test-device").hexdigest())
  else:
    opened.assert_not_called()
