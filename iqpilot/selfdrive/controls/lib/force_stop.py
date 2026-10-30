"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
from iqpilot.cereal import messaging
from iqpilot.common.params import Params
from iqpilot.common.realtime import DT_MDL
from iqpilot.selfdrive.controls.lib.helpers.signal_filter import SignalFilter

FORCE_STOPS_PARAM = "IQForceStops"
MODEL_STOP_TIME_PARAM = "IQDynamicModelStopTime"
MINIMUM_FORCE_STOP_LENGTH_PARAM = "IQDynamicMinimumForceStopLength"

MODEL_HORIZON_INDEX = 33
LEAD_LOCK_GATE = 0.45
CRUISING_SPEED = 3.0
MODEL_STOP_THRESHOLD = 0.55
MODEL_STOP_TIME_DEFAULT = 3.0
MINIMUM_FORCE_STOP_LENGTH_DEFAULT = 0.0
PARAM_REFRESH_FRAMES = int(1. / DT_MDL)


class ForceStopDetector:
  def __init__(self, params=None):
    self.params = params or Params()
    self.lead_filter = SignalFilter(measurement_noise=0.17, process_noise=0.04, process_decay=1.03, smoothing_floor=0.9)
    self.model_stop_filter = SignalFilter(measurement_noise=0.15, process_noise=0.06, process_decay=1.01, smoothing_floor=0.7)
    self.frame = 0
    self.enabled = True
    self.model_stop_time = MODEL_STOP_TIME_DEFAULT
    self.minimum_force_stop_length = MINIMUM_FORCE_STOP_LENGTH_DEFAULT
    self.tracking_lead = False
    self.model_stopped = False
    self.stop_light_detected = False
    self.model_length = 0.0

  def _read_float(self, key: str, default: float) -> float:
    value = self.params.get(key)
    if value is None:
      return default
    if isinstance(value, bytes):
      value = value.decode('utf-8')
    try:
      return float(value)
    except (TypeError, ValueError):
      return default

  def _refresh_params(self) -> None:
    if self.frame % PARAM_REFRESH_FRAMES != 0:
      return
    self.enabled = bool(self.params.get_bool(FORCE_STOPS_PARAM))
    self.model_stop_time = self._read_float(MODEL_STOP_TIME_PARAM, MODEL_STOP_TIME_DEFAULT)
    self.minimum_force_stop_length = self._read_float(MINIMUM_FORCE_STOP_LENGTH_PARAM, MINIMUM_FORCE_STOP_LENGTH_DEFAULT)

  def update(self, sm: messaging.SubMaster) -> None:
    self._refresh_params()
    model = sm['modelV2']
    v_ego = float(sm['carState'].vEgo)

    self.lead_filter.push(float(getattr(sm['radarState'].leadOne, "status", False)))
    self.tracking_lead = (self.lead_filter.value() or 0.0) > LEAD_LOCK_GATE

    if len(model.position.x) == MODEL_HORIZON_INDEX and len(model.orientation.x) == MODEL_HORIZON_INDEX:
      self.model_length = float(model.position.x[MODEL_HORIZON_INDEX - 1])
    else:
      self.model_length = 0.0

    should_stop = bool(getattr(getattr(model, "action", None), "shouldStop", False))
    model_stopping = 0.0 < self.model_length < max(v_ego * self.model_stop_time, CRUISING_SPEED)
    self.model_stopped = bool(should_stop or model_stopping)
    self.model_stop_filter.push(float(self.model_stopped and not self.tracking_lead))
    self.stop_light_detected = (self.model_stop_filter.value() or 0.0) >= MODEL_STOP_THRESHOLD
    self.frame += 1

  def requested(self) -> bool:
    return bool(self.enabled and self.stop_light_detected and self.model_stopped and not self.tracking_lead)
