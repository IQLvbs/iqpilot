from __future__ import annotations

import copy
import importlib.util
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import cereal.messaging as messaging
import numpy as np
from cereal import log

from openpilot.iqpilot.models.split_model_constants import SplitModelConstants
from openpilot.iqpilot.selfdrive.iqmodeld.config import Meta, ModelConstants
from openpilot.iqpilot.selfdrive.iqmodeld.messaging import (
  DrivePacketMemory,
  pick_curvature,
  populate_drive_messages,
  populate_odometry_message,
)
from openpilot.iqpilot.selfdrive.iqmodeld.metadata import build_metadata_record
from openpilot.iqpilot.selfdrive.iqmodeld.parser import ArchiveParser, PhaseParser


REPO_ROOT = Path(__file__).resolve().parents[4]


def _existing_history_ref(repo_path: str) -> str:
  history = subprocess.check_output(
    ["git", "rev-list", "HEAD", "--", repo_path],
    cwd=REPO_ROOT,
    text=True,
  ).splitlines()
  for commit in history:
    probe = subprocess.run(
      ["git", "cat-file", "-e", f"{commit}:{repo_path}"],
      cwd=REPO_ROOT,
      text=True,
      capture_output=True,
    )
    if probe.returncode == 0:
      return f"{commit}:{repo_path}"
  raise FileNotFoundError(f"unable to locate historical source for {repo_path}")


def _load_head_module(repo_path: str, module_name: str, replacements: list[tuple[str, str]]):
  source = subprocess.check_output(["git", "show", _existing_history_ref(repo_path)], cwd=REPO_ROOT, text=True)
  for old, new in replacements:
    source = source.replace(old, new)
  with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
    handle.write(source)
    temp_path = handle.name
  spec = importlib.util.spec_from_file_location(module_name, temp_path)
  module = importlib.util.module_from_spec(spec)
  sys.modules[module_name] = module
  assert spec.loader is not None
  spec.loader.exec_module(module)
  return module


def _combined_sample(rng: np.random.Generator) -> dict[str, np.ndarray]:
  return {
    "plan": rng.standard_normal((1, ModelConstants.PLAN_MHP_N * (2 * ModelConstants.IDX_N * ModelConstants.PLAN_WIDTH + ModelConstants.PLAN_MHP_SELECTION)), dtype=np.float32),
    "lane_lines": rng.standard_normal((1, 2 * ModelConstants.NUM_LANE_LINES * ModelConstants.IDX_N * ModelConstants.LANE_LINES_WIDTH), dtype=np.float32),
    "road_edges": rng.standard_normal((1, 2 * ModelConstants.NUM_ROAD_EDGES * ModelConstants.IDX_N * ModelConstants.LANE_LINES_WIDTH), dtype=np.float32),
    "pose": rng.standard_normal((1, 2 * ModelConstants.POSE_WIDTH), dtype=np.float32),
    "road_transform": rng.standard_normal((1, 2 * ModelConstants.POSE_WIDTH), dtype=np.float32),
    "sim_pose": rng.standard_normal((1, 2 * ModelConstants.POSE_WIDTH), dtype=np.float32),
    "wide_from_device_euler": rng.standard_normal((1, 2 * ModelConstants.WIDE_FROM_DEVICE_WIDTH), dtype=np.float32),
    "lead": rng.standard_normal((1, SplitModelConstants.LEAD_MHP_N * (2 * SplitModelConstants.LEAD_TRAJ_LEN * SplitModelConstants.LEAD_WIDTH + SplitModelConstants.LEAD_MHP_SELECTION)), dtype=np.float32),
    "lat_planner_solution": rng.standard_normal((1, 2 * ModelConstants.IDX_N * ModelConstants.LAT_PLANNER_SOLUTION_WIDTH), dtype=np.float32),
    "desired_curvature": rng.standard_normal((1, 2 * ModelConstants.DESIRED_CURV_WIDTH), dtype=np.float32),
    "lead_prob": rng.standard_normal((1, ModelConstants.LEAD_MHP_SELECTION), dtype=np.float32),
    "lane_lines_prob": rng.standard_normal((1, ModelConstants.NUM_LANE_LINES * 2), dtype=np.float32),
    "meta": rng.standard_normal((1, 55), dtype=np.float32),
    "desire_state": rng.standard_normal((1, ModelConstants.DESIRE_PRED_WIDTH), dtype=np.float32),
    "desire_pred": rng.standard_normal((1, ModelConstants.DESIRE_PRED_LEN * ModelConstants.DESIRE_PRED_WIDTH), dtype=np.float32),
  }


def _split_sample(rng: np.random.Generator) -> dict[str, np.ndarray]:
  return {
    "pose": rng.standard_normal((1, 2 * SplitModelConstants.POSE_WIDTH), dtype=np.float32),
    "wide_from_device_euler": rng.standard_normal((1, 2 * SplitModelConstants.WIDE_FROM_DEVICE_WIDTH), dtype=np.float32),
    "road_transform": rng.standard_normal((1, 2 * SplitModelConstants.POSE_WIDTH), dtype=np.float32),
    "lead": rng.standard_normal((1, SplitModelConstants.LEAD_MHP_N * (2 * SplitModelConstants.LEAD_TRAJ_LEN * SplitModelConstants.LEAD_WIDTH + SplitModelConstants.LEAD_MHP_SELECTION)), dtype=np.float32),
    "plan": rng.standard_normal((1, SplitModelConstants.PLAN_MHP_N * (2 * SplitModelConstants.IDX_N * SplitModelConstants.PLAN_WIDTH + SplitModelConstants.PLAN_MHP_SELECTION)), dtype=np.float32),
    "planplus": rng.standard_normal((1, 2 * SplitModelConstants.IDX_N * SplitModelConstants.PLAN_WIDTH), dtype=np.float32),
    "action": rng.standard_normal((1, 2 * SplitModelConstants.ACTION_WIDTH), dtype=np.float32),
    "desired_curvature": rng.standard_normal((1, 2 * SplitModelConstants.DESIRED_CURV_WIDTH), dtype=np.float32),
    "desire_pred": rng.standard_normal((1, SplitModelConstants.DESIRE_PRED_LEN * SplitModelConstants.DESIRE_PRED_WIDTH), dtype=np.float32),
    "desire_state": rng.standard_normal((1, SplitModelConstants.DESIRE_PRED_WIDTH), dtype=np.float32),
    "lane_lines": rng.standard_normal((1, 2 * SplitModelConstants.NUM_LANE_LINES * SplitModelConstants.IDX_N * SplitModelConstants.LANE_LINES_WIDTH), dtype=np.float32),
    "lane_lines_prob": rng.standard_normal((1, SplitModelConstants.NUM_LANE_LINES * 2), dtype=np.float32),
    "lead_prob": rng.standard_normal((1, SplitModelConstants.LEAD_MHP_SELECTION), dtype=np.float32),
    "lat_planner_solution": rng.standard_normal((1, 2 * SplitModelConstants.IDX_N * SplitModelConstants.LAT_PLANNER_SOLUTION_WIDTH), dtype=np.float32),
    "meta": rng.standard_normal((1, 55), dtype=np.float32),
    "road_edges": rng.standard_normal((1, 2 * SplitModelConstants.NUM_ROAD_EDGES * SplitModelConstants.IDX_N * SplitModelConstants.LANE_LINES_WIDTH), dtype=np.float32),
    "sim_pose": rng.standard_normal((1, 2 * SplitModelConstants.POSE_WIDTH), dtype=np.float32),
  }


def _xyz_snapshot(builder) -> dict[str, list[float]]:
  payload = {
    "t": list(builder.t),
    "x": list(builder.x),
    "y": list(builder.y),
    "z": list(builder.z),
  }
  for name in ("xStd", "yStd", "zStd"):
    if hasattr(builder, name):
      payload[name] = list(getattr(builder, name))
  return payload


def _xyva_snapshot(builder) -> dict[str, list[float] | float]:
  payload = {
    "t": list(builder.t),
    "x": list(builder.x),
    "y": list(builder.y),
    "v": list(builder.v),
    "a": list(builder.a),
    "prob": float(builder.prob),
    "probTime": float(builder.probTime),
  }
  for name in ("xStd", "yStd", "vStd", "aStd"):
    payload[name] = list(getattr(builder, name))
  return payload


def _action_snapshot(builder) -> dict[str, float | bool]:
  return {
    "desiredCurvature": float(builder.desiredCurvature),
    "desiredAcceleration": float(builder.desiredAcceleration),
    "shouldStop": bool(builder.shouldStop),
  }


def _drive_packet_snapshot(msg) -> dict:
  packet = msg.drivingModelData
  return {
    "frameId": int(packet.frameId),
    "frameIdExtra": int(packet.frameIdExtra),
    "frameDropPerc": float(packet.frameDropPerc),
    "modelExecutionTime": float(packet.modelExecutionTime),
    "action": _action_snapshot(packet.action),
    "path": {
      "xCoefficients": list(packet.path.xCoefficients),
      "yCoefficients": list(packet.path.yCoefficients),
      "zCoefficients": list(packet.path.zCoefficients),
    },
    "laneLineMeta": {
      "leftY": float(packet.laneLineMeta.leftY),
      "leftProb": float(packet.laneLineMeta.leftProb),
      "rightY": float(packet.laneLineMeta.rightY),
      "rightProb": float(packet.laneLineMeta.rightProb),
    },
  }


def _model_packet_snapshot(msg) -> dict:
  packet = msg.modelV2
  meta = packet.meta
  disengage = meta.disengagePredictions
  return {
    "frameId": int(packet.frameId),
    "frameIdExtra": int(packet.frameIdExtra),
    "frameAge": int(packet.frameAge),
    "frameDropPerc": float(packet.frameDropPerc),
    "timestampEof": int(packet.timestampEof),
    "modelExecutionTime": float(packet.modelExecutionTime),
    "action": _action_snapshot(packet.action),
    "position": _xyz_snapshot(packet.position),
    "velocity": _xyz_snapshot(packet.velocity),
    "acceleration": _xyz_snapshot(packet.acceleration),
    "orientation": _xyz_snapshot(packet.orientation),
    "orientationRate": _xyz_snapshot(packet.orientationRate),
    "temporalPose": {
      "trans": list(packet.temporalPoseDEPRECATED.trans),
      "transStd": list(packet.temporalPoseDEPRECATED.transStd),
      "rot": list(packet.temporalPoseDEPRECATED.rot),
      "rotStd": list(packet.temporalPoseDEPRECATED.rotStd),
    },
    "laneLines": [_xyz_snapshot(line) for line in packet.laneLines],
    "laneLineStds": list(packet.laneLineStds),
    "laneLineProbs": list(packet.laneLineProbs),
    "roadEdges": [_xyz_snapshot(edge) for edge in packet.roadEdges],
    "roadEdgeStds": list(packet.roadEdgeStds),
    "leadsV3": [_xyva_snapshot(lead) for lead in packet.leadsV3],
    "meta": {
      "desireState": list(meta.desireState),
      "desirePrediction": list(meta.desirePrediction),
      "engagedProb": float(meta.engagedProb),
      "hardBrakePredicted": bool(meta.hardBrakePredicted),
      "t": list(disengage.t),
      "brakeDisengageProbs": list(disengage.brakeDisengageProbs),
      "gasDisengageProbs": list(disengage.gasDisengageProbs),
      "steerOverrideProbs": list(disengage.steerOverrideProbs),
      "brake3MetersPerSecondSquaredProbs": list(disengage.brake3MetersPerSecondSquaredProbs),
      "brake4MetersPerSecondSquaredProbs": list(disengage.brake4MetersPerSecondSquaredProbs),
      "brake5MetersPerSecondSquaredProbs": list(disengage.brake5MetersPerSecondSquaredProbs),
      "gasPressProbs": list(disengage.gasPressProbs) if hasattr(disengage, "gasPressProbs") else [],
      "brakePressProbs": list(disengage.brakePressProbs) if hasattr(disengage, "brakePressProbs") else [],
    },
    "confidence": int(packet.confidence.raw),
  }


def _odometry_snapshot(msg) -> dict:
  odo = msg.cameraOdometry
  return {
    "frameId": int(odo.frameId),
    "timestampEof": int(odo.timestampEof),
    "trans": list(odo.trans),
    "rot": list(odo.rot),
    "wideFromDeviceEuler": list(odo.wideFromDeviceEuler),
    "roadTransformTrans": list(odo.roadTransformTrans),
    "transStd": list(odo.transStd),
    "rotStd": list(odo.rotStd),
    "wideFromDeviceEulerStd": list(odo.wideFromDeviceEulerStd),
    "roadTransformTransStd": list(odo.roadTransformTransStd),
  }


def _stable_snapshot(value):
  if isinstance(value, dict):
    return {key: _stable_snapshot(inner) for key, inner in value.items()}
  if isinstance(value, list):
    return [_stable_snapshot(inner) for inner in value]
  if isinstance(value, float) and math.isnan(value):
    return "nan"
  return value


def test_parser_behavior_matches_head_modeld_v2():
  old_combined = _load_head_module(
    "iqpilot/modeld_v2/parse_model_outputs.py",
    "head_old_combined_parser",
    [("from openpilot.iqpilot.modeld_v2.constants import ModelConstants",
      "from openpilot.iqpilot.selfdrive.iqmodeld.config import ModelConstants")],
  )
  old_split = _load_head_module(
    "iqpilot/modeld_v2/parse_model_outputs_split.py",
    "head_old_split_parser",
    [],
  )

  rng = np.random.default_rng(7)
  old_combined_result = old_combined.Parser().parse_outputs(copy.deepcopy(_combined_sample(rng)))
  new_combined_result = ArchiveParser().parse_outputs(copy.deepcopy(_combined_sample(np.random.default_rng(7))))
  assert old_combined_result.keys() == new_combined_result.keys()
  for key in old_combined_result:
    np.testing.assert_allclose(old_combined_result[key], new_combined_result[key], rtol=1e-6, atol=1e-6)

  split_sample = _split_sample(rng)
  old_split_vision = old_split.Parser().parse_vision_outputs(copy.deepcopy(split_sample))
  new_split_vision = PhaseParser().parse_vision_outputs(copy.deepcopy(split_sample))
  assert old_split_vision.keys() == new_split_vision.keys()
  for key in old_split_vision:
    np.testing.assert_allclose(old_split_vision[key], new_split_vision[key], rtol=1e-6, atol=1e-6)

  old_split_policy = old_split.Parser().parse_policy_outputs(copy.deepcopy(split_sample))
  new_split_policy = PhaseParser().parse_policy_outputs(copy.deepcopy(split_sample))
  assert old_split_policy.keys() == new_split_policy.keys()
  for key in old_split_policy:
    np.testing.assert_allclose(old_split_policy[key], new_split_policy[key], rtol=1e-6, atol=1e-6)


def test_metadata_record_matches_head_modeld_v2_builder():
  old_metadata = _load_head_module(
    "iqpilot/modeld_v2/get_model_metadata.py",
    "head_old_metadata",
    [],
  )
  model_path = REPO_ROOT / "selfdrive" / "modeld" / "models" / "driving_vision.onnx"
  old_record = old_metadata.make_metadata_dict(model_path)
  new_record = build_metadata_record(model_path)
  assert old_record == new_record


def test_message_population_matches_head_modeld_v2():
  old_messaging = _load_head_module(
    "iqpilot/modeld_v2/fill_model_msg.py",
    "head_old_messaging",
    [("from openpilot.iqpilot.modeld_v2.constants import ModelConstants, Plan",
      "from openpilot.iqpilot.selfdrive.iqmodeld.config import ModelConstants, Plan")],
  )

  raw_outputs = copy.deepcopy(_split_sample(np.random.default_rng(23)))
  outputs = {
    **PhaseParser().parse_vision_outputs(copy.deepcopy(raw_outputs)),
    **PhaseParser().parse_policy_outputs(copy.deepcopy(raw_outputs)),
  }
  action = log.ModelDataV2.Action(desiredCurvature=0.031, desiredAcceleration=-0.12, shouldStop=False)

  old_drive = messaging.new_message("drivingModelData")
  new_drive = messaging.new_message("drivingModelData")
  old_model = messaging.new_message("modelV2")
  new_model = messaging.new_message("modelV2")
  old_pose = messaging.new_message("cameraOdometry")
  new_pose = messaging.new_message("cameraOdometry")

  old_state = old_messaging.PublishState()
  new_state = DrivePacketMemory()

  kwargs = dict(
    vipc_frame_id=2468,
    vipc_frame_id_extra=2470,
    frame_id=2480,
    frame_drop=0.05,
    timestamp_eof=123456789,
    model_execution_time=0.014,
    valid=True,
  )

  meta_layout = Meta

  old_messaging.fill_model_msg(
    old_drive,
    old_model,
    outputs,
    action,
    old_state,
    kwargs["vipc_frame_id"],
    kwargs["vipc_frame_id_extra"],
    kwargs["frame_id"],
    kwargs["frame_drop"],
    kwargs["timestamp_eof"],
    kwargs["model_execution_time"],
    kwargs["valid"],
    meta_layout,
  )
  populate_drive_messages(
    new_drive,
    new_model,
    outputs,
    action,
    new_state,
    kwargs["vipc_frame_id"],
    kwargs["vipc_frame_id_extra"],
    kwargs["frame_id"],
    kwargs["frame_drop"],
    kwargs["timestamp_eof"],
    kwargs["model_execution_time"],
    kwargs["valid"],
    meta_layout,
  )

  old_messaging.fill_pose_msg(
    old_pose,
    outputs,
    kwargs["vipc_frame_id"],
    0,
    kwargs["timestamp_eof"],
    True,
  )
  populate_odometry_message(
    new_pose,
    outputs,
    kwargs["vipc_frame_id"],
    0,
    kwargs["timestamp_eof"],
    True,
  )

  assert old_drive.valid == new_drive.valid
  assert old_model.valid == new_model.valid
  assert old_pose.valid == new_pose.valid
  assert _stable_snapshot(_drive_packet_snapshot(old_drive)) == _stable_snapshot(_drive_packet_snapshot(new_drive))
  assert _stable_snapshot(_model_packet_snapshot(old_model)) == _stable_snapshot(_model_packet_snapshot(new_model))
  assert _stable_snapshot(_odometry_snapshot(old_pose)) == _stable_snapshot(_odometry_snapshot(new_pose))
  np.testing.assert_allclose(old_state.disengage_buffer, new_state.disengage_rollup)
  np.testing.assert_allclose(old_state.prev_brake_5ms2_probs, new_state.brake_watch_5)
  np.testing.assert_allclose(old_state.prev_brake_3ms2_probs, new_state.brake_watch_3)


def test_curvature_picker_matches_head_modeld_v2():
  old_messaging = _load_head_module(
    "iqpilot/modeld_v2/fill_model_msg.py",
    "head_old_messaging_curvature",
    [("from openpilot.iqpilot.modeld_v2.constants import ModelConstants, Plan",
      "from openpilot.iqpilot.selfdrive.iqmodeld.config import ModelConstants, Plan")],
  )

  parsed = PhaseParser().parse_policy_outputs(copy.deepcopy(_split_sample(np.random.default_rng(31))))
  plan_rows = parsed["plan"][0]

  new_direct = pick_curvature(parsed, plan_rows, 27.5, 0.8, synthetic_lane_logic=False)
  old_direct = old_messaging.get_curvature_from_output(parsed, plan_rows, 27.5, 0.8, False)
  np.testing.assert_allclose(new_direct, old_direct)

  new_fallback = pick_curvature(parsed, plan_rows, 27.5, 0.8, synthetic_lane_logic=True)
  old_fallback = old_messaging.get_curvature_from_output(parsed, plan_rows, 27.5, 0.8, True)
  np.testing.assert_allclose(new_fallback, old_fallback)
