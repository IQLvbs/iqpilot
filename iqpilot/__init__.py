"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import sys
from pathlib import Path

_LOADER_SHIMS = Path(__file__).resolve().parents[1] / "scripts" / "iqpilot" / "ci_shims"
if sys.platform != "linux" and _LOADER_SHIMS.is_dir():
  __path__.append(str(_LOADER_SHIMS))
