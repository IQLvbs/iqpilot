"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import base64
import os
import pickle
from types import SimpleNamespace

import numpy as np
import pytest

os.environ["DEV"] = "CPU"

onnx = pytest.importorskip("onnx")
ort = pytest.importorskip("onnxruntime")

from onnx import TensorProto, helper, numpy_helper

from iqpilot.system.camerad.cameras.nv12_info import get_nv12_info
from iqpilot.selfdrive.iqmodeld.models.runners import model_runner as model_runner_mod
from iqpilot.selfdrive.iqmodeld.models.runners.tinygrad import stateful_runner as stateful_mod
from iqpilot.selfdrive.iqmodeld.tools import compile_stateful_supercombo as css
from iqpilot.selfdrive.iqmodeld.tools import compile_supercombo as cs

H, W, IMG_Q, DESIRE_Q, FEAT_Q, F = 4, 8, 5, 6, 4, 16
CAM = (64, 48)
SLICES = {"pose": slice(0, 12), "wide_from_device_euler": slice(12, 18), "road_transform": slice(18, 30),
          "hidden_state": slice(30, 46), "pad": slice(46, 48)}
OUT_LEN = 48
INPUTS = {
  "new_img": ((2, 6, H, W), TensorProto.UINT8),
  "desire": ((8,), TensorProto.FLOAT),
  "traffic_convention": ((1, 2), TensorProto.FLOAT),
  "action_t": ((1, 2), TensorProto.FLOAT),
  "state_img_q": ((2, IMG_Q, 6, H, W), TensorProto.UINT8),
  "state_desire_q": ((DESIRE_Q, 1, 8), TensorProto.FLOAT),
  "state_feat_q": ((FEAT_Q, 1, F), TensorProto.FLOAT),
}


def _i64(name, values):
  return helper.make_node("Constant", [], [name], value=helper.make_tensor(name + "_v", TensorProto.INT64, [len(values)], values))


def _f32(name, array):
  return helper.make_node("Constant", [], [name], value=numpy_helper.from_array(np.asarray(array, dtype=np.float32), name + "_v"))


def _stateful_onnx(path, slices=SLICES):
  rng = np.random.default_rng(3)
  x_len = 2 * IMG_Q + DESIRE_Q * 8 + FEAT_Q * F + 4
  nodes = [
    _i64("one", [1]), _i64("big", [1 << 30]), _i64("ax0", [0]), _i64("ax1", [1]),
    _i64("row", [1, -1]), _i64("feat_row", [1, 1, F]), _i64("desire_row", [1, 1, 8]),
    _f32("w", rng.standard_normal((x_len, F)) * 0.1), _f32("b", rng.standard_normal((1, F)) * 0.1),
    _f32("w2", rng.standard_normal((F, 30)) * 0.5), _f32("pad", np.zeros((1, 2))), _f32("img_scale", [1 / 255.0]),
    helper.make_node("Unsqueeze", ["new_img", "ax1"], ["new_img_q"]),
    helper.make_node("Slice", ["state_img_q", "one", "big", "ax1"], ["older_img"]),
    helper.make_node("Concat", ["older_img", "new_img_q"], ["next_state_img_q"], axis=1),
    helper.make_node("Reshape", ["desire", "desire_row"], ["desire_r"]),
    helper.make_node("Slice", ["state_desire_q", "one", "big", "ax0"], ["older_desire"]),
    helper.make_node("Concat", ["older_desire", "desire_r"], ["next_state_desire_q"], axis=0),
    helper.make_node("Cast", ["next_state_img_q"], ["img_f"], to=TensorProto.FLOAT),
    helper.make_node("ReduceMean", ["img_f"], ["img_m"], axes=[2, 3, 4], keepdims=0),
    helper.make_node("Mul", ["img_m", "img_scale"], ["img_s"]),
    helper.make_node("Reshape", ["img_s", "row"], ["img_row"]),
    helper.make_node("Reshape", ["next_state_desire_q", "row"], ["desire_hist"]),
    helper.make_node("Reshape", ["state_feat_q", "row"], ["feat_hist"]),
    helper.make_node("Concat", ["img_row", "desire_hist", "feat_hist", "traffic_convention", "action_t"], ["x"], axis=1),
    helper.make_node("MatMul", ["x", "w"], ["xw"]),
    helper.make_node("Add", ["xw", "b"], ["xwb"]),
    helper.make_node("Tanh", ["xwb"], ["h"]),
    helper.make_node("Reshape", ["h", "feat_row"], ["h_q"]),
    helper.make_node("Slice", ["state_feat_q", "one", "big", "ax0"], ["older_feat"]),
    helper.make_node("Concat", ["older_feat", "h_q"], ["next_state_feat_q"], axis=0),
    helper.make_node("MatMul", ["h", "w2"], ["heads"]),
    helper.make_node("Concat", ["heads", "h", "pad"], ["outputs"], axis=1),
  ]
  inputs = [helper.make_tensor_value_info(n, t, list(s)) for n, (s, t) in INPUTS.items()]
  outputs = [helper.make_tensor_value_info("outputs", TensorProto.FLOAT, [1, OUT_LEN])]
  outputs += [helper.make_tensor_value_info("next_" + n, INPUTS[n][1], list(INPUTS[n][0]))
              for n in ("state_img_q", "state_desire_q", "state_feat_q")]
  model = helper.make_model(helper.make_graph(nodes, "stateful_supercombo", inputs, outputs), opset_imports=[helper.make_opsetid("", 17)])
  model.ir_version = 8
  helper.set_model_props(model, {"output_slices": base64.b64encode(pickle.dumps(slices)).decode(), "model_checkpoint": "fake/1"})
  onnx.save(model, path)


def _ort_steps(onnx_path, frames, host):
  sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
  state = {n: np.zeros(s, dtype=np.uint8 if t == TensorProto.UINT8 else np.float32) for n, (s, t) in INPUTS.items() if n.startswith("state_")}
  outs = []
  for frame, values in zip(frames, host, strict=True):
    result = dict(zip([o.name for o in sess.get_outputs()], sess.run(None, {"new_img": frame, **values, **state}), strict=True))
    outs.append(result["outputs"].reshape(-1))
    state = {n: result["next_" + n] for n in state}
  return outs


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
  onnx_path = str(tmp_path_factory.mktemp("stateful") / "m.onnx")
  _stateful_onnx(onnx_path)
  artifact = css.compile_stateful(onnx_path, [CAM], expected_device="CPU", validate=False)
  return onnx_path, pickle.loads(pickle.dumps(artifact))


def test_metadata_pairs_state_queues_and_packs_host_inputs(compiled):
  onnx_path, artifact = compiled
  meta = artifact["metadata"]
  assert artifact["format"] == meta["format"] == css.STATEFUL_FORMAT
  assert meta["state_pairs"] == {n: "next_" + n for n in ("state_img_q", "state_desire_q", "state_feat_q")}
  assert meta["host_inputs"] == {"desire": (8,), "traffic_convention": (1, 2), "action_t": (1, 2)}
  assert meta["output_slices"] == SLICES and meta["model_checkpoint"] == "fake/1" and meta["output_len"] == OUT_LEN
  assert css.frame_size(meta) == (2 * W, 2 * H)
  assert set(artifact) == {"format", "metadata", "run_policy", CAM}


def test_metadata_pkl_is_pure_python(compiled):
  _, artifact = compiled

  class _Strict(pickle.Unpickler):
    def find_class(self, module, name):
      if (module, name) == ("builtins", "slice"):
        return slice
      raise AssertionError(f"metadata references {module}.{name}")

  import io
  assert _Strict(io.BytesIO(pickle.dumps(artifact["metadata"]))).load() == artifact["metadata"]


def test_output_slices_decoder_refuses_anything_but_slices():
  class _Evil:
    def __reduce__(self):
      return (os.getcwd, ())
  with pytest.raises(pickle.UnpicklingError):
    css.decode_output_slices(base64.b64encode(pickle.dumps({"plan": _Evil()})).decode())
  assert css.decode_output_slices(base64.b64encode(pickle.dumps(SLICES)).decode()) == SLICES


def test_output_head_concat_is_split_into_its_own_kernels():
  from tinygrad.tensor import Tensor
  runner = css.isolate_output_heads(SimpleNamespace(onnx_ops={"Concat": None, "Gemm": "gemm"}))
  heads = [np.full((1, 3), i, np.float32) for i in range(css.HEAD_CONCAT_MIN_INPUTS)]
  queue = [np.zeros((2, 1, 4), np.float32), np.ones((1, 1, 4), np.float32)]
  out = runner.onnx_ops["Concat"](*[Tensor(h) for h in heads], axis=1)
  assert runner.onnx_ops["Gemm"] == "gemm"
  np.testing.assert_array_equal(out.numpy(), np.concatenate(heads, axis=1))
  np.testing.assert_array_equal(runner.onnx_ops["Concat"](*[Tensor(q) for q in queue], axis=0).numpy(), np.concatenate(queue, axis=0))


def test_metadata_rejects_graphs_without_state_or_with_mismatched_state():
  props = {"output_slices": base64.b64encode(pickle.dumps(SLICES)).decode()}
  inputs = {"new_img": ((2, 6, H, W), "uint8"), "desire": ((8,), "float32"), "state_feat_q": ((4, 1, F), "float32")}
  with pytest.raises(ValueError, match="no state input"):
    css.build_stateful_metadata(inputs, {"outputs": ((1, OUT_LEN), "float32")}, props)
  with pytest.raises(ValueError, match="does not match"):
    css.build_stateful_metadata(inputs, {"outputs": ((1, OUT_LEN), "float32"), "next_state_feat_q": ((5, 1, F), "float32")}, props)
  with pytest.raises(ValueError, match="overrun"):
    css.build_stateful_metadata(inputs, {"outputs": ((1, 40), "float32"), "next_state_feat_q": ((4, 1, F), "float32")}, props)


def test_stateful_jit_matches_ort_over_twenty_frames_with_state_carried(compiled):
  onnx_path, artifact = compiled
  meta = artifact["metadata"]
  frames, host = css.stateful_test_inputs(meta, 24)
  got = css._run_steps(artifact["run_policy"], meta, frames, host)
  want = _ort_steps(onnx_path, frames, host)
  for step, (g, w) in enumerate(zip(got, want, strict=True)):
    np.testing.assert_allclose(g, w, atol=1e-5, rtol=1e-5, err_msg=f"step {step}")
  assert not np.allclose(want[0], want[-1])


def _frame_buf(rng):
  size = get_nv12_info(*CAM)[3]
  return SimpleNamespace(data=rng.integers(0, 256, size, dtype=np.uint8), width=CAM[0], height=CAM[1])


def _runner(artifact):
  runner = stateful_mod.TinygradStatefulRunner.__new__(stateful_mod.TinygradStatefulRunner)
  runner._parser = stateful_mod.PhaseParser()
  runner._constants = stateful_mod.SplitModelConstants
  runner._bind(artifact)
  return runner


def test_runner_carries_state_pulses_desire_and_matches_ort(compiled):
  from tinygrad.tensor import Tensor
  onnx_path, artifact = compiled
  runner = _runner(artifact)
  nv12 = cs.NV12Frame(*CAM, *get_nv12_info(*CAM))
  warp_ref = cs.make_warp(nv12, 2 * W, 2 * H, 1)
  rng = np.random.default_rng(11)
  eye = np.eye(3, dtype=np.float32)

  frames, host, got = [], [], []
  held = np.zeros(8, dtype=np.float32)
  prev = np.zeros(8, dtype=np.float32)
  for step in range(20):
    bufs = {"img": _frame_buf(rng), "big_img": _frame_buf(rng)}
    held[:] = 0
    if 4 <= step < 9:
      held[3] = 1
    tc = np.array([[0.0, 1.0]], dtype=np.float32)
    at = np.array([[0.2, 0.1 * step]], dtype=np.float32)
    result = runner.run_fused(bufs, {"img": eye, "big_img": eye}, {"desire_pulse": held.copy(), "traffic_convention": tc, "action_t": at})
    got.append(result["hidden_state"].reshape(-1).copy())
    warped = warp_ref(Tensor(eye), Tensor(eye), Tensor(bufs["img"].data), Tensor(bufs["big_img"].data)).numpy()
    frames.append(warped)
    pulse = np.where(held - prev > 0.99, held, 0).astype(np.float32)
    prev = held.copy()
    host.append({"desire": pulse, "traffic_convention": tc, "action_t": at})
    assert pulse.sum() == (1.0 if step == 4 else 0.0)

  want = _ort_steps(onnx_path, frames, host)
  for step, (g, w) in enumerate(zip(got, want, strict=True)):
    np.testing.assert_allclose(g, w[SLICES["hidden_state"]], atol=1e-5, rtol=1e-5, err_msg=f"step {step}")

  runner.reset_state()
  for state in runner._states.values():
    assert not state.numpy().any()
  assert not runner._prev_desire.any()


def test_runner_exposes_a_daemon_compatible_input_view(compiled):
  _, artifact = compiled
  runner = _runner(artifact)
  shapes = runner.input_shapes
  assert shapes["img"] == shapes["big_img"] == (1, 12, H, W)
  assert shapes["desire_pulse"][0] == 1 and shapes["desire_pulse"][1] > 1 and shapes["desire_pulse"][2] == 8
  assert shapes["traffic_convention"] == (1, 2) and shapes["action_t"] == (1, 2)
  assert not any(name.startswith("state_") for name in shapes)
  assert "pad" not in runner.output_slices and runner.vision_input_names == ["img", "big_img"]


def test_runner_refuses_foreign_artifacts_and_mismatched_jits(compiled):
  _, artifact = compiled
  runner = stateful_mod.TinygradStatefulRunner.__new__(stateful_mod.TinygradStatefulRunner)
  with pytest.raises(ValueError, match="iq-stateful-supercombo-v1"):
    runner._bind({"run_policy": object(), "metadata": {}})

  bad = dict(artifact)
  bad["metadata"] = {**artifact["metadata"], "state_pairs": {"state_feat_q": "next_state_feat_q"}}
  with pytest.raises(RuntimeError, match="JIT contract mismatch"):
    _runner(bad)


def test_stateful_bundles_get_the_stateful_runner(monkeypatch):
  from iqpilot.selfdrive.iqmodeld.models.runners.model_runner import ModelType

  def bundle(name):
    return SimpleNamespace(models=[SimpleNamespace(type=SimpleNamespace(raw=ModelType.supercombo),
                                                   artifact=SimpleNamespace(fileName=name))])

  stateful = bundle("driving_stateful_ch_driving_tinygrad.pkl.iqc")
  plain = bundle("driving_supercombo_tsf_tinygrad.pkl.iqc")
  assert model_runner_mod._is_stateful_bundle(stateful) and not model_runner_mod._is_supercombo_bundle(stateful)
  assert model_runner_mod._is_supercombo_bundle(plain) and not model_runner_mod._is_stateful_bundle(plain)

  built = []
  monkeypatch.setattr(model_runner_mod, "_fetch_bundle", lambda: stateful)
  monkeypatch.setattr(model_runner_mod, "_optional_private_runner", lambda b: None)
  monkeypatch.setattr(stateful_mod.TinygradStatefulRunner, "__init__", lambda self: built.append(self))
  assert isinstance(model_runner_mod.get_model_runner(), stateful_mod.TinygradStatefulRunner) and built
