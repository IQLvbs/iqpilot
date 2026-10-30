# Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
from iqpilot._proprietary_loader import ProprietaryModuleMissing, load_private_module

try:
  load_private_module(__name__, "iqpilot_private.context.speed_limit_input")
except ProprietaryModuleMissing:
  MAX_SPEED_LIMIT_AGE_S = 2.0
  SPEED_LIMIT_INPUT_SHAPE = (1, 4)

  def speed_limit_unit_is_mph(params) -> bool:
    return not params.get_bool("IsMetric")

  def device_speed_limit_input(numpy_inputs, sub, params, frame_timestamp_eof_ns: int, force_enabled: bool = False):
    import numpy as np
    target = numpy_inputs.get("speed_limit_input")
    return {} if target is None else {"speed_limit_input": np.zeros(target.shape, dtype=np.float32)}
