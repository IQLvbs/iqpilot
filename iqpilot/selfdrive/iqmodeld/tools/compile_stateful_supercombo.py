#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""

import argparse
import base64
import io
import math
import os
import pickle
from functools import partial

import numpy as np

from iqpilot.selfdrive.iqmodeld.tools import compile_supercombo as cs

from tinygrad.tensor import Tensor
from tinygrad.device import Device
from tinygrad.engine.jit import TinyJit

STATEFUL_FORMAT = "iq-stateful-supercombo-v1"
FRAME_INPUT = "new_img"
NEXT_PREFIX = "next_"
PACKED_INPUT = "packed_npy_inputs"
WARPED_INPUT = "warped"
WARP_INPUTS = ["tfm", "big_tfm"]
HEAD_CONCAT_MIN_INPUTS = 8


class _SliceOnlyUnpickler(pickle.Unpickler):
  def find_class(self, module, name):
    if module == "builtins" and name == "slice":
      return slice
    raise pickle.UnpicklingError(f"output_slices may only hold slices, found {module}.{name}")


def decode_output_slices(encoded: str) -> dict[str, slice]:
  slices = _SliceOnlyUnpickler(io.BytesIO(base64.b64decode(encoded))).load()
  if not isinstance(slices, dict) or not all(isinstance(k, str) and isinstance(v, slice) for k, v in slices.items()):
    raise ValueError("output_slices is not a dict of named slices")
  return slices


def stateful_metadata(model_path: str) -> dict:
  from iqpilot.selfdrive.iqmodeld.metadata import TelemetryEnvelopeParser
  parsed = TelemetryEnvelopeParser(model_path).parse()

  def table(field):
    return {vi["name"]: (tuple(int(d) for d in vi["parsed_type"].shape), np.dtype(vi["parsed_type"].dtype.fmt).name)
            for vi in parsed["graph"][field]}
  props = {entry["key"]: entry["value"] for entry in parsed["metadata_props"]}
  return build_stateful_metadata(table("input"), table("output"), props)


def build_stateful_metadata(inputs: dict, outputs: dict, props: dict) -> dict:
  if FRAME_INPUT not in inputs:
    raise ValueError(f"stateful supercombo needs a {FRAME_INPUT} input, got {sorted(inputs)}")
  if "outputs" not in outputs:
    raise ValueError(f"stateful supercombo needs an outputs tensor, got {sorted(outputs)}")
  state_pairs = {name: NEXT_PREFIX + name for name in inputs if NEXT_PREFIX + name in outputs}
  if not state_pairs:
    raise ValueError("onnx has no state input with a next_<name> output; use compile_supercombo.py")
  for name, next_name in state_pairs.items():
    if inputs[name] != outputs[next_name]:
      raise ValueError(f"state {name} {inputs[name]} does not match {next_name} {outputs[next_name]}")
  extra_outputs = set(outputs) - {"outputs", *state_pairs.values()}
  if extra_outputs:
    raise ValueError(f"unsupported extra outputs {sorted(extra_outputs)}")

  frame_shape, frame_dtype = inputs[FRAME_INPUT]
  if len(frame_shape) != 4 or frame_shape[0] != 2 or frame_shape[1] != 6 or frame_dtype != "uint8":
    raise ValueError(f"{FRAME_INPUT} must be uint8 [2, 6, H, W] (road then wide), got {frame_dtype} {list(frame_shape)}")
  host_inputs = {name: shape for name, (shape, dtype) in inputs.items() if name != FRAME_INPUT and name not in state_pairs}
  for name in host_inputs:
    if inputs[name][1] != "float32":
      raise ValueError(f"host input {name} must be float32, got {inputs[name][1]}")

  output_slices = decode_output_slices(props["output_slices"])
  output_len = outputs["outputs"][0][-1]
  if max(s.stop for s in output_slices.values()) > output_len:
    raise ValueError(f"output_slices overrun the {output_len}-wide outputs tensor")

  return {
    "format": STATEFUL_FORMAT,
    "model_checkpoint": props.get("model_checkpoint"),
    "output_slices": output_slices,
    "output_len": output_len,
    "input_shapes": {name: shape for name, (shape, _) in inputs.items()},
    "input_dtypes": {name: dtype for name, (_, dtype) in inputs.items()},
    "output_shapes": {name: shape for name, (shape, _) in outputs.items()},
    "state_pairs": state_pairs,
    "host_inputs": host_inputs,
  }


def packed_layout(metadata: dict) -> tuple[dict[str, tuple[int, ...]], list[int]]:
  shapes = {name: tuple(shape) for name, shape in metadata["host_inputs"].items()}
  return shapes, [math.prod(s) for s in shapes.values()]


def frame_size(metadata: dict) -> tuple[int, int]:
  _, _, h, w = metadata["input_shapes"][FRAME_INPUT]
  return int(w) * 2, int(h) * 2


def make_model_queues(metadata: dict, device):
  shapes, sizes = packed_layout(metadata)
  packed = np.zeros(sum(sizes), dtype=np.float32)
  npy = {name: view.reshape(shape) for (name, shape), view in zip(shapes.items(), np.split(packed, np.cumsum(sizes[:-1])), strict=True)}
  queues = {
    name: Tensor(np.zeros(metadata["input_shapes"][name], dtype=metadata["input_dtypes"][name]), device=device).contiguous().realize()
    for name in metadata["state_pairs"]
  }
  queues[PACKED_INPUT] = Tensor(packed, device="NPY").realize()
  return queues, npy


def make_warp_queues(device):
  npy = {name: np.zeros((3, 3), dtype=np.float32) for name in WARP_INPUTS}
  return {name: Tensor(value, device="NPY").realize() for name, value in npy.items()}, npy


def isolate_output_heads(model_runner):
  def concat(*xs, axis: int):
    # every head's final Gemm fused into one a630 output kernel (Qualcomm CL compiler) returns wrong ch-driving desire_state lanes 1-7
    return Tensor.cat(*[x.contiguous() if len(xs) >= HEAD_CONCAT_MIN_INPUTS else x for x in xs], dim=axis)
  model_runner.onnx_ops = {**model_runner.onnx_ops, "Concat": concat}
  return model_runner


def model_input_keys(metadata: dict) -> list[str]:
  return [PACKED_INPUT, *metadata["state_pairs"]]


def make_run_model(model_runner, metadata: dict):
  shapes, sizes = packed_layout(metadata)
  state_pairs = dict(metadata["state_pairs"])
  state_dtypes = {name: metadata["input_dtypes"][name] for name in state_pairs}

  def run_model(warped, packed_npy_inputs, **states):
    packed_npy_inputs = packed_npy_inputs.to(Device.DEFAULT)
    warped = warped.to(Device.DEFAULT)
    Tensor.realize(packed_npy_inputs, warped)

    host = {name: t.reshape(s) for (name, s), t in zip(shapes.items(), packed_npy_inputs.split(sizes), strict=True)}
    outputs = model_runner({FRAME_INPUT: warped, **host, **states})
    out = outputs["outputs"].cast("float32").contiguous()
    nexts = [outputs[next_name].cast(state_dtypes[name]).contiguous() for name, next_name in state_pairs.items()]
    Tensor.realize(out, *nexts)
    for name, value in zip(state_pairs, nexts, strict=True):
      states[name].assign(value)
    Tensor.realize(*(states[name] for name in state_pairs))
    return out,
  return run_model


def _run_steps(fn, metadata: dict, frames: list[np.ndarray], host: list[dict[str, np.ndarray]]) -> list[np.ndarray]:
  queues, npy = make_model_queues(metadata, Device.DEFAULT)
  outs = []
  for frame, values in zip(frames, host, strict=True):
    for name, value in values.items():
      npy[name][:] = value
    warped = Tensor(frame, device=Device.DEFAULT).realize()
    out, = fn(warped=warped, **{k: queues[k] for k in model_input_keys(metadata)})
    outs.append(out.numpy().reshape(-1).copy())
  return outs


def stateful_test_inputs(metadata: dict, steps: int, seed: int = 7) -> tuple[list[np.ndarray], list[dict[str, np.ndarray]]]:
  rng = np.random.default_rng(seed)
  frame_shape = metadata["input_shapes"][FRAME_INPUT]
  frames = [rng.integers(0, 256, size=frame_shape, dtype=np.uint8) for _ in range(steps)]
  shapes, _ = packed_layout(metadata)
  host = []
  for step in range(steps):
    values = {name: np.zeros(shape, dtype=np.float32) for name, shape in shapes.items()}
    if "desire" in values and step % 7 == 3:
      values["desire"].reshape(-1)[1 + step % (values["desire"].size - 1)] = 1.0
    if "traffic_convention" in values:
      values["traffic_convention"].reshape(-1)[0] = 1.0
    if "action_t" in values:
      values["action_t"].reshape(-1)[:] = [0.3, 0.6][:values["action_t"].size]
    host.append(values)
  return frames, host


def validate_stateful_release(run_model_jit, model_runner, metadata: dict, expected_device: str, steps: int = 4) -> None:
  frames, host = stateful_test_inputs(metadata, steps)
  jit_outs = _run_steps(run_model_jit, metadata, frames, host)
  direct_outs = _run_steps(make_run_model(model_runner, metadata), metadata, frames, host)
  for step, (direct, jit) in enumerate(zip(direct_outs, jit_outs, strict=True)):
    if not np.isfinite(jit).all():
      raise AssertionError(f"JIT stateful output is not finite at step {step}")
    if not np.allclose(direct, jit, atol=1e-4, rtol=1e-4):
      delta = float(np.max(np.abs(direct - jit)))
      raise AssertionError(f"JIT stateful output diverges from direct ONNX execution at step {step}; max abs delta {delta}")
  if np.array_equal(jit_outs[0], jit_outs[-1]):
    raise AssertionError("stateful outputs did not change across steps; state is not being carried")

  from iqpilot.selfdrive.iqmodeld.parser import PhaseParser
  parsed = PhaseParser().parse_vision_outputs(cs._slice_outputs(jit_outs[-1], metadata["output_slices"]))
  cs._validate_pose_outputs(parsed)

  captured_devices = cs._captured_devices(run_model_jit)
  if expected_device and captured_devices and expected_device not in captured_devices:
    raise AssertionError(f"compiled run_policy backend mismatch: captured {sorted(captured_devices)} expected {expected_device}")


def compile_stateful(model_path: str, camera_resolutions, expected_device: str = "QCOM", validate: bool = True) -> dict:
  from tinygrad.nn.onnx import OnnxRunner
  from iqpilot.system.camerad.cameras.nv12_info import get_nv12_info

  metadata = stateful_metadata(model_path)
  model_runner = isolate_output_heads(OnnxRunner(model_path))
  out = {"format": STATEFUL_FORMAT, "metadata": metadata}

  frame_shape = metadata["input_shapes"][FRAME_INPUT]
  run_model_jit = TinyJit(make_run_model(model_runner, metadata), prune=True)
  out["run_policy"] = cs.compile_jit(
    run_model_jit,
    partial(cs.make_random_images, keys=[WARPED_INPUT], shape=tuple(frame_shape)),
    model_input_keys(metadata),
    partial(make_model_queues, metadata),
  )
  if validate:
    validate_stateful_release(out["run_policy"], model_runner, metadata, expected_device)

  model_w, model_h = frame_size(metadata)
  for cam_w, cam_h in camera_resolutions:
    nv12 = cs.NV12Frame(cam_w, cam_h, *get_nv12_info(cam_w, cam_h))
    warp_jit = TinyJit(cs.make_warp(nv12, model_w, model_h, 1), prune=True)
    out[(cam_w, cam_h)] = cs.compile_jit(
      warp_jit,
      partial(cs.make_random_images, keys=["frame", "big_frame"], shape=nv12.size, device=cs.WARP_DEV),
      WARP_INPUTS,
      make_warp_queues,
    )
    captured_devices = cs._captured_devices(out[(cam_w, cam_h)])
    if expected_device and captured_devices and expected_device not in captured_devices:
      raise AssertionError(f"compiled warp backend mismatch for {cam_w}x{cam_h}: captured {sorted(captured_devices)} expected {expected_device}")
  return out


if __name__ == "__main__":
  p = argparse.ArgumentParser(description="compile a stateful supercombo onnx (new_img + state_*/next_state_*) into one pkl")
  p.add_argument("--camera-resolutions", type=cs._parse_size, nargs="+", required=True, help="camera resolutions WxH")
  p.add_argument("--onnx", required=True)
  p.add_argument("--output", required=True)
  p.add_argument("--expected-device", default="QCOM", help="expected tinygrad backend baked into the JIT")
  p.add_argument("--skip-validation", action="store_true", help="skip the direct-vs-JIT and pose checks")
  args = p.parse_args()

  compiled = compile_stateful(cs.read_file_chunked_to_shm(args.onnx), args.camera_resolutions, args.expected_device,
                              validate=not args.skip_validation)
  with open(args.output, "wb") as f:
    pickle.dump(compiled, f)
  print(f"Saved JITs to {args.output} ({os.path.getsize(args.output) / 1e6:.2f} MB)")
