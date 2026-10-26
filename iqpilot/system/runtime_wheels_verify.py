#!/usr/bin/env python3
import csv
import sys
from importlib import metadata
from pathlib import Path

from iqpilot.system.runtime_wheel_requirements import PACKAGE_NAMES


missing = []
for name in PACKAGE_NAMES:
  try:
    dist = metadata.distribution(name)
  except metadata.PackageNotFoundError:
    missing.append(f"{name}: not installed")
    continue
  record = dist.read_text("RECORD")
  if not record:
    missing.append(f"{name}: no RECORD")
    continue
  base = Path(str(dist._path)).parent
  for row in csv.reader(record.splitlines()):
    if not row or row[0].endswith((".pyc", "/")):
      continue
    if not (base / row[0]).exists():
      missing.append(f"{name}: {row[0]}")

if missing:
  print("\n".join(missing[:20]), file=sys.stderr)
  print(f"runtime wheels damaged: {len(missing)} missing files", file=sys.stderr)
  sys.exit(1)
