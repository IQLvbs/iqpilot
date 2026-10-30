"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
"""

import numpy as np
import pytest

from iqpilot.selfdrive.iqmodeld.daemon import MemoryResetTracker, NeuralEngineState, ReplayLedger


def test_rank_two_feedback_copies_and_invalid_feedback_resets():
  ledger = ReplayLedger({"memory_state": (1, 192)}, [])
  source = np.ones((1, 192), np.float32)
  ledger.note_feedback("memory_state", source)
  source.fill(2)
  np.testing.assert_array_equal(ledger.inputs["memory_state"], np.ones((1, 192), np.float32))
  with pytest.raises(ValueError):
    ledger.note_feedback("memory_state", np.ones((192,), np.float32))
  assert not ledger.inputs["memory_state"].any()


def test_memory_reset_tracker_rejects_discontinuities_and_edges():
  tracker = MemoryResetTracker()
  assert tracker.update(10, 1_000_000_000, False, False)
  assert not tracker.update(11, 1_050_000_000, False, False)
  assert tracker.update(13, 1_100_000_000, False, False)
  assert tracker.update(14, 1_150_000_000, True, False)
  assert not tracker.update(15, 1_200_000_000, True, True)
  assert tracker.update(16, 1_250_000_000, True, False)
  assert tracker.update(17, 1_250_000_000, True, False)
  assert tracker.update(18, 1_400_000_001, True, False)


def test_fused_runtime_feeds_back_memory_and_reset_clears_it():
  class Runner:
    uses_opencl_warp = False
    output_slices = {"memory_state_out": slice(2578, 2770)}

    def __init__(self):
      self.seen = []

    def run_fused(self, vision_bufs, transform_map, fresh_inputs):
      state = fresh_inputs["memory_state"].copy()
      self.seen.append(state)
      return {"memory_state_out": state + 1}

  runtime = object.__new__(NeuralEngineState)
  runtime.model_runner = Runner()
  runtime._ledger = ReplayLedger({"memory_state": (1, 192)}, [])
  runtime.numpy_inputs = runtime._ledger.inputs
  runtime.has_memory_carry = True
  runtime.run({}, {}, {})
  runtime.run({}, {}, {})
  runtime.reset_memory()
  runtime.run({}, {}, {})
  assert not runtime.model_runner.seen[0].any()
  assert (runtime.model_runner.seen[1] == 1).all()
  assert not runtime.model_runner.seen[2].any()
