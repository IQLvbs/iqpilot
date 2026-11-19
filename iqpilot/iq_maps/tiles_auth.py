#!/usr/bin/env python3
"""
Copyright (c) IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
from iqpilot._proprietary_loader import ProprietaryModuleMissing, load_private_module

try:
  load_private_module(__name__, "iqpilot_private.maps.git_auth")
except ProprietaryModuleMissing:
  from iqpilot.maps_private_src.git_auth import *
