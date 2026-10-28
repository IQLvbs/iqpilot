# Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from iqpilot import _proprietary_loader
from iqpilot.selfdrive.iqmodeld import daemon


@pytest.fixture
def fallback(monkeypatch):
  calls = []

  def missing(public_name, private_name):
    calls.append(private_name)
    raise _proprietary_loader.ProprietaryModuleMissing("missing model context")

  monkeypatch.setattr(_proprietary_loader, "load_private_module", missing)
  spec = importlib.util.spec_from_file_location("model_context_fallback_test", Path(daemon.__file__).with_name("model_context.py"))
  module = importlib.util.module_from_spec(spec)
  monkeypatch.setitem(sys.modules, spec.name, module)
  spec.loader.exec_module(module)
  assert calls == ["iqpilot_private.context.model_context"]
  return module


def fake_daemon(has_context):
  shapes = {"desire_pulse": (1, 25, 8), "traffic_convention": (1, 2), "action_t": (1, 2),
            "lateral_control_params": (1, 2), "extra_context": (1, 32)}
  ledger = daemon.ReplayLedger(shapes, [])
  instance = daemon.InferenceDaemon.__new__(daemon.InferenceDaemon)
  instance._runtime = SimpleNamespace(numpy_inputs=ledger.inputs, desire_key=ledger.pulse_name,
                                      constants=SimpleNamespace(DESIRE_LEN=8), has_context=has_context)
  instance._desire_logic = SimpleNamespace(desire=0)
  instance._sub = {"driverMonitoringState": SimpleNamespace(isRHD=False)}
  instance._params = None
  instance._feature_inputs = daemon.FeatureInputComposer({"input_shapes": shapes})
  return instance, ledger


def test_missing_bundle_keeps_extra_inputs_zero(fallback, monkeypatch):
  instance, ledger = fake_daemon(False)
  assert fallback.context_model({key: value.shape for key, value in ledger.inputs.items()}) is False
  assert fallback.device_context_inputs(ledger.inputs, None, 1) == {}

  def unexpected(*args):
    pytest.fail("context inputs called for a model without context")

  monkeypatch.setattr(daemon, "device_context_inputs", unexpected)
  inputs = instance._compose_inputs(12.0, 0.2, 0.4, 123)
  ledger.merge_inputs(inputs)
  assert not ledger.inputs["extra_context"].any()
  np.testing.assert_array_equal(ledger.inputs["traffic_convention"], [[1, 0]])
  np.testing.assert_allclose(ledger.inputs["action_t"], [[0.2, 0.4]])
  np.testing.assert_allclose(ledger.inputs["lateral_control_params"], [[12.0, 0.2]])


def test_fallback_composer_is_safe_when_called(fallback, monkeypatch):
  instance, ledger = fake_daemon(True)
  monkeypatch.setattr(daemon, "device_context_inputs", fallback.device_context_inputs)
  ledger.merge_inputs(instance._compose_inputs(12.0, 0.2, 0.4, 123))
  assert not ledger.inputs["extra_context"].any()


def test_composed_context_inputs_reach_ledger(monkeypatch):
  instance, ledger = fake_daemon(True)
  expected = np.full((1, 32), 0.5, dtype=np.float32)

  def compose(numpy_inputs, sub, timestamp):
    assert numpy_inputs is ledger.inputs
    assert sub is instance._sub
    assert timestamp == 123
    return {"extra_context": expected}

  monkeypatch.setattr(daemon, "device_context_inputs", compose)
  ledger.merge_inputs(instance._compose_inputs(12.0, 0.2, 0.4, 123))
  np.testing.assert_array_equal(ledger.inputs["extra_context"], expected)


@pytest.mark.parametrize("has_context", [False, True])
def test_runtime_detects_context_once(monkeypatch, has_context):
  shapes = {"desire_pulse": (1, 25, 8), "extra_context": (1, 32)}
  runner = SimpleNamespace(input_shapes=shapes, vision_input_names=[], is_20hz=True,
                           constants=SimpleNamespace(DESIRE_LEN=8))
  calls = []

  def detect(input_shapes):
    calls.append(input_shapes)
    return has_context

  monkeypatch.setattr(daemon, "get_model_runner", lambda: runner)
  monkeypatch.setattr(daemon, "get_active_bundle", lambda: None)
  monkeypatch.setattr(daemon, "context_model", detect)
  monkeypatch.setattr(daemon, "device_context_inputs", lambda *args: {})
  runtime = daemon.NeuralEngineState(None)
  assert runtime.has_context is has_context
  instance, _ = fake_daemon(has_context)
  instance._runtime = runtime
  for timestamp in (123, 456):
    instance._compose_inputs(12.0, 0.2, 0.4, timestamp)
  assert calls == [shapes]
