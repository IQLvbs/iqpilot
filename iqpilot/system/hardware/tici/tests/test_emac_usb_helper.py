"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""
import subprocess

from iqpilot.system.hardware.tici import usb_storage


class _Done:
  def __init__(self, returncode):
    self.returncode = returncode


def _record(monkeypatch, helper: bool, returncode: int = 0):
  calls = []
  monkeypatch.setattr(usb_storage.os, "access", lambda path, mode: helper and path == usb_storage.EMAC_USB_HELPER)

  def fake_run(args, **kwargs):
    calls.append(args)
    return _Done(returncode)

  monkeypatch.setattr(usb_storage.subprocess, "run", fake_run)
  return calls


def test_prepare_pins_the_port_through_the_os_helper(monkeypatch):
  calls = _record(monkeypatch, helper=True)
  assert usb_storage.prepare_emac_usb()
  assert calls == [["sudo", "-n", usb_storage.EMAC_USB_HELPER, "up"]]


def test_prepare_reports_a_failed_helper(monkeypatch):
  _record(monkeypatch, helper=True, returncode=1)
  assert not usb_storage.prepare_emac_usb()


def test_egpu_input_suspend_never_changes_the_port_role(monkeypatch):
  calls = _record(monkeypatch, helper=True)
  assert usb_storage.suspend_usb_input(True)
  assert usb_storage.suspend_usb_input(False)
  assert calls == [["sudo", "-n", usb_storage.EMAC_USB_HELPER, "suspend-input"],
                   ["sudo", "-n", usb_storage.EMAC_USB_HELPER, "down"]]


def test_images_without_the_helper_keep_the_sudo_write(monkeypatch):
  calls = _record(monkeypatch, helper=False)
  monkeypatch.setattr(usb_storage.os.path, "exists", lambda path: path == usb_storage.INPUT_SUSPEND)
  monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError()))
  assert usb_storage.prepare_emac_usb()
  assert calls == [["sudo", "-n", "sh", "-c", f"echo 1 > {usb_storage.INPUT_SUSPEND}"]]


def test_helper_timeout_is_a_failure(monkeypatch):
  monkeypatch.setattr(usb_storage.os, "access", lambda path, mode: True)

  def hang(args, **kwargs):
    raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))

  monkeypatch.setattr(usb_storage.subprocess, "run", hang)
  assert usb_storage.run_emac_usb_helper("up") == -1
