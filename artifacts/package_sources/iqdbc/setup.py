import os
from pathlib import Path
import sys

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
  def run(self):
    super().run()

    source_root = Path(self.get_package_dir("iqdbc")).resolve().parent
    sys.path.insert(0, str(source_root))
    previous_pythonpath = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, (str(source_root), previous_pythonpath)))

    try:
      from iqdbc.dbc.generator.generator import create_all

      create_all(str(Path(self.build_lib) / "iqdbc" / "dbc"))
    finally:
      sys.path.remove(str(source_root))
      if previous_pythonpath is None:
        del os.environ["PYTHONPATH"]
      else:
        os.environ["PYTHONPATH"] = previous_pythonpath


setup(cmdclass={"build_py": build_py})
