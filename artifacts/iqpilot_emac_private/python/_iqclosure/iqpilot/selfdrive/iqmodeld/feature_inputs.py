# Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos/
from iqpilot._proprietary_loader import ProprietaryModuleMissing, load_private_module

try:
  load_private_module(__name__, "iqpilot_private.context.feature_inputs")
except ProprietaryModuleMissing:
  class FeatureInputComposer:
    services = []

    def __init__(self, metadata):
      self.metadata = metadata
      self.uses_resolver = metadata.get("speed_limit_contract") == "rh-speed-limit-v1"
      self.uses_drive_profile = metadata.get("drive_profile_contract") == "rh-drive-profile-v1"

    def compose(self, sub, params, frame_timestamp_eof_ns, vehicle_speed, inputs):
      import numpy as np
      names = {"map_tile"} | ({"speed_limit_input"} if self.uses_resolver else set()) | ({"drive_profile"} if self.uses_drive_profile else set())
      return {name: np.zeros(shape, dtype=np.uint8 if name == "map_tile" else np.float32)
              for name, shape in self.metadata.get("input_shapes", {}).items()
              if name in names}, None
