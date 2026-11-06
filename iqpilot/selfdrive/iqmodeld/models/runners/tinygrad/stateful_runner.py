"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from __future__ import annotations

import math
import os
from typing import Any

import numpy as np

from iqpilot.selfdrive.iqmodeld.models.runners.model_runner import (
  CUSTOM_MODEL_PATH, ModelRunner, NumpyDict, ShapeDict, SliceDict, load_big_model_pickle,
)
from iqpilot.selfdrive.iqmodeld.models.runners.tinygrad.supercombo_runner import (
  _captured_devices, _captured_expected_names, _file_sha256,
)
from iqpilot.selfdrive.iqmodeld.models.split_model_constants import SplitModelConstants
from iqpilot.selfdrive.iqmodeld.parser import PhaseParser

STATEFUL_FORMAT = "iq-stateful-supercombo-v1"
STATEFUL_ARTIFACT_PREFIX = "driving_stateful_"
STATEFUL_BUNDLE_MIN_SELECTOR_VERSION = 21
FRAME_INPUT = "new_img"
PACKED_INPUT = "packed_npy_inputs"
WARP_NAMES = ["big_frame", "big_tfm", "frame", "tfm"]
DESIRE_PULSE_HISTORY = 25


def _tinygrad_imports():
  from tinygrad.tensor import Tensor
  from tinygrad.device import Device
  return Tensor, Device


class TinygradStatefulRunner(ModelRunner):
  uses_opencl_warp: bool = False

  def __init__(self):
    super().__init__()
    self._constants = SplitModelConstants
    self._parser = PhaseParser()

    if len(self.models) != 1:
      raise ValueError(f"stateful bundle must have exactly one artifact, got {list(self.models)}")
    self._model_data = next(iter(self.models.values()))

    self._pkl_path = os.path.join(CUSTOM_MODEL_PATH, self._model_data.model.artifact.fileName)
    self._expected_sha256 = getattr(getattr(self._model_data.model.artifact, "downloadUri", None), "sha256", "") or ""
    self._verify_artifact_file()
    self._bind(load_big_model_pickle(self._pkl_path))

  def _bind(self, artifact: Any) -> None:
    if not isinstance(artifact, dict) or artifact.get("format") != STATEFUL_FORMAT:
      found = artifact.get("format") if isinstance(artifact, dict) else type(artifact).__name__
      raise ValueError(f"artifact is not {STATEFUL_FORMAT}: {found}")
    self._meta: dict = artifact["metadata"]
    self._state_names = list(self._meta["state_pairs"])
    self._host_shapes = {name: tuple(shape) for name, shape in self._meta["host_inputs"].items()}
    self._slices = {k: v for k, v in self._meta["output_slices"].items() if k != "pad"}
    self._run_policy = artifact["run_policy"]
    self._warp_jits: dict[tuple[int, int], Any] = {k: v for k, v in artifact.items() if isinstance(k, tuple)}
    if not self._warp_jits:
      raise ValueError("stateful pkl has no warp JITs")
    self._validate_jits()

    desire_len = self._host_shapes["desire"][-1] if "desire" in self._host_shapes else SplitModelConstants.DESIRE_LEN
    self._prev_desire = np.zeros(desire_len, dtype=np.float32)
    self._states: dict[str, Any] | None = None
    self._npy: dict[str, np.ndarray] | None = None
    self._host_tensors: dict[str, Any] | None = None
    self._cam: tuple[int, int] | None = None
    self._blob_cache: dict[tuple[str, int], Any] = {}

  def _verify_artifact_file(self) -> None:
    if not self._expected_sha256:
      return
    actual = _file_sha256(self._pkl_path)
    if actual == self._expected_sha256:
      return
    try:
      os.remove(self._pkl_path)
    except OSError:
      pass
    raise RuntimeError(f"stateful artifact SHA mismatch: expected {self._expected_sha256}, got {actual} for {self._pkl_path}; "
                       + "deleted the stale cached file, re-download the model.")

  def _validate_jits(self) -> None:
    mismatches: list[str] = []
    expected_policy = sorted([PACKED_INPUT, "warped", *self._state_names])
    policy_names = sorted(_captured_expected_names(self._run_policy))
    if policy_names and policy_names != expected_policy:
      mismatches.append(f"run_policy captured={policy_names} expected={expected_policy}")

    expected_device = os.getenv("DEV")
    for cam, warp_jit in sorted(self._warp_jits.items()):
      warp_names = sorted(_captured_expected_names(warp_jit))
      if warp_names and warp_names != WARP_NAMES:
        mismatches.append(f"{cam[0]}x{cam[1]} warp captured={warp_names} expected={WARP_NAMES}")
      devices = _captured_devices(warp_jit)
      if expected_device and devices and expected_device not in devices:
        mismatches.append(f"{cam[0]}x{cam[1]} device captured={sorted(devices)} expected={expected_device}")
    if mismatches:
      raise RuntimeError(f"stateful artifact JIT contract mismatch: {'; '.join(mismatches)}. Re-download or rebuild this model artifact.")

  @property
  def vision_input_names(self) -> list[str]:
    return ["img", "big_img"]

  @property
  def input_shapes(self) -> ShapeDict:
    _, channels, h, w = self._meta["input_shapes"][FRAME_INPUT]
    frame = (1, 2 * channels, h, w)
    shapes: ShapeDict = {"img": frame, "big_img": frame,
                         "desire_pulse": (1, DESIRE_PULSE_HISTORY, len(self._prev_desire))}
    shapes.update((name, shape) for name, shape in self._host_shapes.items() if name != "desire")
    return shapes

  @property
  def output_slices(self) -> SliceDict:
    return dict(self._slices)

  @property
  def reasoning_metadata(self) -> dict:
    return {k: v for k, v in self._meta.items() if k != "state_pairs"}

  def prepare_inputs(self, imgs_cl, numpy_inputs, frames):
    raise RuntimeError("stateful runner has no OpenCL path; use run_fused()")

  def _run_model(self) -> NumpyDict:
    raise RuntimeError("stateful path goes through run_fused(), not _run_model()")

  def _frame_tensor(self, key: str, buf):
    Tensor, Device = _tinygrad_imports()
    arr = np.frombuffer(buf.data, dtype=np.uint8)
    ck = (key, arr.ctypes.data)
    t = self._blob_cache.get(ck)
    if t is None:
      t = Tensor.from_blob(arr.ctypes.data, (arr.size,), dtype="uint8", device=Device.DEFAULT)
      self._blob_cache[ck] = t
    return t

  def _ensure_queues(self, cam_w: int, cam_h: int) -> None:
    if self._states is not None and self._cam == (cam_w, cam_h):
      return
    if (cam_w, cam_h) not in self._warp_jits:
      raise RuntimeError(f"no warp JIT for {cam_w}x{cam_h}; have {sorted(self._warp_jits)}")
    Tensor, Device = _tinygrad_imports()

    sizes = [math.prod(s) for s in self._host_shapes.values()]
    packed = np.zeros(sum(sizes), dtype=np.float32)
    views = np.split(packed, np.cumsum(sizes[:-1])) if sizes else []
    self._npy = {name: view.reshape(shape) for (name, shape), view in zip(self._host_shapes.items(), views, strict=True)}
    self._npy["tfm"] = np.zeros((3, 3), dtype=np.float32)
    self._npy["big_tfm"] = np.zeros((3, 3), dtype=np.float32)
    self._host_tensors = {
      PACKED_INPUT: Tensor(packed, device="NPY"),
      "tfm": Tensor(self._npy["tfm"], device="NPY"),
      "big_tfm": Tensor(self._npy["big_tfm"], device="NPY"),
    }
    self._states = {
      name: Tensor(np.zeros(self._meta["input_shapes"][name], dtype=self._meta["input_dtypes"][name]),
                   device=Device.DEFAULT).contiguous().realize()
      for name in self._state_names
    }
    self._prev_desire[:] = 0
    self._cam = (cam_w, cam_h)

  def reset_state(self) -> None:
    if self._states is not None:
      for state in self._states.values():
        state.assign(state.zeros_like()).realize()
    self._prev_desire[:] = 0

  def _stage_host_inputs(self, numpy_inputs: NumpyDict) -> None:
    assert self._npy is not None
    desire_key = next((k for k in numpy_inputs if k.startswith("desire")), None)
    current = np.zeros_like(self._prev_desire)
    if desire_key is not None:
      current[:] = np.asarray(numpy_inputs[desire_key], dtype=np.float32).reshape(-1)[-len(current):]
    current[0] = 0
    if "desire" in self._npy:
      self._npy["desire"].reshape(-1)[:] = np.where(current - self._prev_desire > .99, current, 0)
    self._prev_desire[:] = current
    for name in self._host_shapes:
      if name == "desire":
        continue
      if name in numpy_inputs:
        self._npy[name][:] = np.asarray(numpy_inputs[name], dtype=np.float32).reshape(self._npy[name].shape)
      else:
        self._npy[name].fill(0)

  def run_fused(self, bufs: dict, transforms: dict[str, np.ndarray], numpy_inputs: NumpyDict) -> NumpyDict:
    main_buf = bufs["img"]
    self._ensure_queues(main_buf.width, main_buf.height)
    assert self._states is not None and self._npy is not None and self._host_tensors is not None

    self._npy["tfm"][:] = transforms["img"]
    self._npy["big_tfm"][:] = transforms["big_img"]
    self._stage_host_inputs(numpy_inputs)

    warp = self._warp_jits[self._cam]
    warped = warp(tfm=self._host_tensors["tfm"], big_tfm=self._host_tensors["big_tfm"],
                  frame=self._frame_tensor("img", bufs["img"]), big_frame=self._frame_tensor("big_img", bufs["big_img"]))
    out, = self._run_policy(warped=warped, packed_npy_inputs=self._host_tensors[PACKED_INPUT], **self._states)
    flat = out.numpy().reshape(-1)
    return self._parser.parse_vision_outputs({name: flat[np.newaxis, span] for name, span in self._slices.items()})
