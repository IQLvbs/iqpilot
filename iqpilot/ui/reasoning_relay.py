# Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
from iqpilot._proprietary_loader import ProprietaryModuleMissing, load_private_module

try:
  load_private_module(__name__, "iqpilot_private.context.reasoning_relay")
except ProprietaryModuleMissing:
  class RasterEndpoint:
    def __init__(self, root=None):
      raise ProprietaryModuleMissing("the reasoning display requires the IQ.Pilot proprietary context bundle")
