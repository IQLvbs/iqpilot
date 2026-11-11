"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import os

import pytest

os.environ.setdefault("DEV", "CPU")

from iqpilot.selfdrive.iqmodeld import egpu_helpers


class _Dock:
  def is_usb(self):
    return True


class _StuckSignal:
  owner = _Dock()
  value = 0


def test_driving_timeout_replaces_the_setup_default(monkeypatch):
  monkeypatch.setattr(egpu_helpers, "_usb_signal_timeout_ms", None)
  egpu_helpers.tighten_usb_signal_timeout()
  assert egpu_helpers._usb_signal_timeout_ms == egpu_helpers.USB_DRIVING_SIGNAL_TIMEOUT_MS == 3000


def test_stuck_usb_signal_raises_at_the_tightened_timeout(monkeypatch):
  from tinygrad.runtime.ops_amd import AMDSignal
  egpu_helpers.patch_usb_signal_wait()
  monkeypatch.setattr(egpu_helpers, "_usb_signal_timeout_ms", 5)
  with pytest.raises(RuntimeError, match="Wait timeout: 5 ms"):
    AMDSignal.wait(_StuckSignal(), 1)
