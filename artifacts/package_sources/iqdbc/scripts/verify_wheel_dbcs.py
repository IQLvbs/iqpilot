#!/usr/bin/env python3
import sys
import tempfile
import zipfile
from pathlib import Path


def main() -> None:
  wheel = Path(sys.argv[1]).resolve()
  with tempfile.TemporaryDirectory() as tmp:
    with zipfile.ZipFile(wheel) as archive:
      archive.extractall(tmp)

    sys.path.insert(0, tmp)

    from iqdbc.can.dbc import DBC
    from iqdbc.car.values import PLATFORMS

    referenced = sorted({
      dbc_name
      for platform in PLATFORMS.values()
      for dbc_name in platform.config.dbc_dict.values()
      if dbc_name
    })

    for dbc_name in referenced:
      DBC(dbc_name)

  print(f"validated {len(referenced)} packaged DBCs")


if __name__ == "__main__":
  main()
