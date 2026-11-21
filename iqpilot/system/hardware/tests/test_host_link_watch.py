"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from iqpilot.system.hardware.usb import HostLinkWatch, host_link_configured


def _udc(root, state, name="a600000.usb"):
  d = root / name
  d.mkdir(parents=True)
  (d / "state").write_text(state + "\n")
  return d


class _Clock:
  def __init__(self):
    self.now = 1000.0

  def __call__(self):
    return self.now


def test_missing_udc_dir_is_unknown(tmp_path):
  assert host_link_configured(tmp_path / "absent") is None


def test_empty_udc_dir_is_unknown(tmp_path):
  assert host_link_configured(tmp_path) is None


def test_configured_and_not_attached(tmp_path):
  d = _udc(tmp_path, "configured")
  assert host_link_configured(tmp_path) is True
  (d / "state").write_text("not attached\n")
  assert host_link_configured(tmp_path) is False


def test_watch_fails_open_when_unreadable(tmp_path):
  assert HostLinkWatch(udc_root=tmp_path / "absent").present() is True


def test_watch_never_enumerated_is_absent(tmp_path):
  _udc(tmp_path, "not attached")
  assert HostLinkWatch(udc_root=tmp_path).present() is False


def test_watch_configured_is_present(tmp_path):
  _udc(tmp_path, "configured")
  assert HostLinkWatch(udc_root=tmp_path).present() is True


def test_watch_grace_then_absent(tmp_path):
  d = _udc(tmp_path, "configured")
  clock = _Clock()
  watch = HostLinkWatch(grace_s=60.0, udc_root=tmp_path, clock=clock)
  assert watch.present() is True
  (d / "state").write_text("default\n")
  clock.now += 30
  assert watch.present() is True
  clock.now += 31
  assert watch.present() is False
  (d / "state").write_text("configured\n")
  assert watch.present() is True
