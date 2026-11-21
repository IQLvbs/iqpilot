#!/usr/bin/env python3
"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""

from iqpilot._proprietary_loader import ProprietaryModuleMissing, load_private_module

try:
  load_private_module(__name__, "iqpilot_private.models.iqc")
except ProprietaryModuleMissing:
  from iqpilot.models_private_src.iqc import *  # noqa: F403
