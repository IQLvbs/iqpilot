"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("DEV", "CPU")

from iqpilot.common.transformations.camera import DEVICE_CAMERAS
from iqpilot.common.transformations.model import (
  FULLFRAME_INPUT_SIZE,
  MEDMODEL_INPUT_SIZE,
  fullframe_intrinsics,
  fullframe_wide_intrinsics,
  get_fullframe_intrinsics,
  get_fullframe_warp_matrix,
  model_frame_size,
)
from iqpilot.selfdrive.iqmodeld.tools.compile_supercombo import checked_model_size

DEVICES = [("mici", "os04c10"), ("tizi", "ox03c10"), ("tizi", "os04c10"), ("tici", "ar0231")]


def _corners(width, height):
  return np.array([[0, 0, 1], [width, 0, 1], [0, height, 1], [width, height, 1]], dtype=np.float64)


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("wide", [False, True])
def test_fullframe_warp_is_the_whole_sensor(device, wide):
  cameras = DEVICE_CAMERAS[device]
  camera = cameras.ecam if wide else cameras.fcam
  warp = get_fullframe_warp_matrix(camera.intrinsics, camera.width, camera.height)
  projected = (warp @ _corners(*FULLFRAME_INPUT_SIZE).T).T
  projected = projected[:, :2] / projected[:, 2:]
  np.testing.assert_allclose(projected, _corners(camera.width, camera.height)[:, :2], atol=0.05)


def test_c4_fullframe_intrinsics_match_comma():
  cameras = DEVICE_CAMERAS[("mici", "os04c10")]
  np.testing.assert_allclose(get_fullframe_intrinsics(cameras.fcam.intrinsics, cameras.fcam.width, cameras.fcam.height),
                             fullframe_intrinsics, atol=1e-3)
  np.testing.assert_allclose(get_fullframe_intrinsics(cameras.ecam.intrinsics, cameras.ecam.width, cameras.ecam.height),
                             fullframe_wide_intrinsics, atol=1e-3)


def test_packed_image_shape_maps_to_model_frame():
  assert model_frame_size((1, 12, 128, 256)) == MEDMODEL_INPUT_SIZE
  assert model_frame_size((1, 12, 256, 512)) == FULLFRAME_INPUT_SIZE
  assert model_frame_size((2, 6, 256, 512)) == FULLFRAME_INPUT_SIZE


def test_compile_model_size_must_match_onnx():
  assert checked_model_size((1024, 512), {"img": (1, 12, 256, 512)}) == FULLFRAME_INPUT_SIZE
  assert checked_model_size((512, 256), {"img": (1, 12, 128, 256)}) == MEDMODEL_INPUT_SIZE
  with pytest.raises(SystemExit, match="does not match the onnx img input 1024x512"):
    checked_model_size((512, 256), {"img": (1, 12, 256, 512)})
