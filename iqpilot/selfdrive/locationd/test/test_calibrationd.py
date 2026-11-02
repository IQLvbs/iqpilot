import random

import numpy as np

import pytest

import iqpilot.cereal.messaging as messaging
from iqpilot.cereal import car, log
from iqpilot.common.params import Params
from iqpilot.selfdrive.locationd.calibrationd import Calibrator, INPUTS_NEEDED, INPUTS_WANTED, BLOCK_SIZE, MIN_SPEED_FILTER, \
                                                         MAX_YAW_RATE_FILTER, SMOOTH_CYCLES, HEIGHT_INIT, MAX_ALLOWED_PITCH_SPREAD, MAX_ALLOWED_YAW_SPREAD, \
                                                         discard_calibration_from_other_car


def process_messages(c, cam_odo_calib, cycles,
                     cam_odo_speed=MIN_SPEED_FILTER + 1,
                     carstate_speed=MIN_SPEED_FILTER + 1,
                     cam_odo_yr=0.0,
                     cam_odo_speed_std=1e-3,
                     cam_odo_height_std=1e-3):
  old_rpy_weight_prev = 0.0
  for _ in range(cycles):
    assert (old_rpy_weight_prev - c.old_rpy_weight < 1/SMOOTH_CYCLES + 1e-3)
    old_rpy_weight_prev = c.old_rpy_weight
    c.handle_v_ego(carstate_speed)
    c.handle_cam_odom([cam_odo_speed,
                       np.sin(cam_odo_calib[2]) * cam_odo_speed,
                       -np.sin(cam_odo_calib[1]) * cam_odo_speed],
                        [0.0, 0.0, cam_odo_yr],
                        [0.0, 0.0, 0.0],
                        [cam_odo_speed_std, cam_odo_speed_std, cam_odo_speed_std],
                        [0.0, 0.0, HEIGHT_INIT.item()],
                        [cam_odo_height_std, cam_odo_height_std, cam_odo_height_std])

class FakeParams:
  def __init__(self, values: dict[str, bytes]):
    self.values = dict(values)

  def get(self, key: str):
    return self.values.get(key)

  def remove(self, key: str) -> None:
    self.values.pop(key, None)


def car_params(fingerprint: str, brand: str):
  CP = car.CarParams.new_message()
  CP.carFingerprint = fingerprint
  CP.brand = brand
  return CP


@pytest.mark.parametrize("prev, current, kept", [
  (("HONDA_PILOT", "honda"), ("HONDA_PILOT", "honda"), True),
  (("HONDA_PILOT", "honda"), ("HONDA_ACCORD", "honda"), False),
  (("TOYOTA_RAV4", "toyota"), ("HONDA_ACCORD", "honda"), False),
  (("HONDA_PILOT", "honda"), ("MOCK", "mock"), True),
  (("MOCK", "mock"), ("HONDA_PILOT", "honda"), True),
  (None, ("HONDA_PILOT", "honda"), True),
])
def test_discard_calibration_from_other_car(prev, current, kept):
  values = {"CalibrationParams": b"saved"}
  if prev is not None:
    values["CarParamsPrevRoute"] = car_params(*prev).to_bytes()
  params = FakeParams(values)

  discard_calibration_from_other_car(params, car_params(*current))

  assert (params.get("CalibrationParams") == b"saved") == kept


def test_discard_calibration_keeps_it_when_prev_route_unreadable():
  params = FakeParams({"CalibrationParams": b"saved", "CarParamsPrevRoute": b"not a capnp message"})

  discard_calibration_from_other_car(params, car_params("HONDA_PILOT", "honda"))

  assert params.get("CalibrationParams") == b"saved"


class TestCalibrationd:
  def test_read_saved_params(self):
    msg = messaging.new_message('extrinsicsCalibration')
    msg.extrinsicsCalibration.validBlocks = random.randint(1, 10)
    msg.extrinsicsCalibration.rpyCalib = [0.0, 0.01, 0.01]
    msg.extrinsicsCalibration.height = HEIGHT_INIT.tolist()
    Params().put("CalibrationParams", msg.to_bytes())
    c = Calibrator(param_put=True)

    np.testing.assert_allclose(msg.extrinsicsCalibration.rpyCalib, c.rpy)
    np.testing.assert_allclose(msg.extrinsicsCalibration.height, c.height)
    assert msg.extrinsicsCalibration.validBlocks == c.valid_blocks


  def test_calibration_basics(self):
    c = Calibrator(param_put=False)
    process_messages(c, [0.0, 0.0, 0.0], BLOCK_SIZE * INPUTS_WANTED)
    assert c.valid_blocks == INPUTS_WANTED
    np.testing.assert_allclose(c.rpy, np.zeros(3))
    np.testing.assert_allclose(c.height, HEIGHT_INIT)
    c.reset()


  def test_calibration_low_speed_reject(self):
    c = Calibrator(param_put=False)
    process_messages(c, [0.0, 0.0, 0.0], BLOCK_SIZE * INPUTS_WANTED, carstate_speed=MIN_SPEED_FILTER - 1)
    assert c.valid_blocks == 0
    np.testing.assert_allclose(c.rpy, np.zeros(3))
    np.testing.assert_allclose(c.height, HEIGHT_INIT)

    c = Calibrator(param_put=False)
    process_messages(c, [0.0, 0.0, 0.0], BLOCK_SIZE * INPUTS_WANTED,
                     cam_odo_speed=MIN_SPEED_FILTER - 10, carstate_speed=MIN_SPEED_FILTER + 5)
    assert c.valid_blocks == INPUTS_WANTED
    np.testing.assert_allclose(c.rpy[1:], np.zeros(2), atol=1e-6)
    np.testing.assert_allclose(c.height, HEIGHT_INIT)


  def test_calibration_yaw_rate_reject(self):
    c = Calibrator(param_put=False)
    process_messages(c, [0.0, 0.0, 0.0], BLOCK_SIZE * INPUTS_WANTED, cam_odo_yr=MAX_YAW_RATE_FILTER)
    assert c.valid_blocks == 0
    np.testing.assert_allclose(c.rpy, np.zeros(3))
    np.testing.assert_allclose(c.height, HEIGHT_INIT)


  def test_calibration_speed_std_reject(self):
    c = Calibrator(param_put=False)
    process_messages(c, [0.0, 0.0, 0.0], BLOCK_SIZE * INPUTS_WANTED, cam_odo_speed_std=1e3)
    assert c.valid_blocks == 0
    np.testing.assert_allclose(c.rpy, np.zeros(3))


  def test_calibration_speed_std_height_reject(self):
    c = Calibrator(param_put=False)
    process_messages(c, [0.0, 0.0, 0.0], BLOCK_SIZE * INPUTS_WANTED, cam_odo_height_std=1e3)
    assert c.valid_blocks == INPUTS_WANTED
    np.testing.assert_allclose(c.rpy, np.zeros(3))


  def test_calibration_auto_reset(self):
    c = Calibrator(param_put=False)
    process_messages(c, [0.0, 0.0, 0.0], BLOCK_SIZE * INPUTS_NEEDED)
    assert c.valid_blocks == INPUTS_NEEDED
    np.testing.assert_allclose(c.rpy, [0.0, 0.0, 0.0], atol=1e-3)
    process_messages(c, [0.0, MAX_ALLOWED_PITCH_SPREAD*0.9, MAX_ALLOWED_YAW_SPREAD*0.9], BLOCK_SIZE + 10)
    assert c.valid_blocks == INPUTS_NEEDED + 1
    assert c.cal_status == log.ExtrinsicsCalibration.Status.calibrated

    c = Calibrator(param_put=False)
    process_messages(c, [0.0, 0.0, 0.0], BLOCK_SIZE * INPUTS_NEEDED)
    assert c.valid_blocks == INPUTS_NEEDED
    np.testing.assert_allclose(c.rpy, [0.0, 0.0, 0.0])
    process_messages(c, [0.0, MAX_ALLOWED_PITCH_SPREAD*1.1, 0.0], BLOCK_SIZE + 10)
    assert c.valid_blocks == 1
    assert c.cal_status == log.ExtrinsicsCalibration.Status.recalibrating
    np.testing.assert_allclose(c.rpy, [0.0, MAX_ALLOWED_PITCH_SPREAD*1.1, 0.0], atol=1e-2)

    c = Calibrator(param_put=False)
    process_messages(c, [0.0, 0.0, 0.0], BLOCK_SIZE * INPUTS_NEEDED)
    assert c.valid_blocks == INPUTS_NEEDED
    np.testing.assert_allclose(c.rpy, [0.0, 0.0, 0.0])
    process_messages(c, [0.0, 0.0, MAX_ALLOWED_YAW_SPREAD*1.1], BLOCK_SIZE + 10)
    assert c.valid_blocks == 1
    assert c.cal_status == log.ExtrinsicsCalibration.Status.recalibrating
    np.testing.assert_allclose(c.rpy, [0.0, 0.0, MAX_ALLOWED_YAW_SPREAD*1.1], atol=1e-2)
