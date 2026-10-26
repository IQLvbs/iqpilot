import os
import platform
import subprocess

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPyWithFirmware(build_py):
  def run(self):
    if not getattr(self, "editable_mode", False) and platform.system() != "Windows":
      subprocess.check_call(["scons", f"-j{os.cpu_count() or 1}", "board/obj"], cwd=os.path.dirname(os.path.abspath(__file__)))
    super().run()
    os.unlink(os.path.join(self.build_lib, "panda", "setup.py"))


setup(cmdclass={"build_py": BuildPyWithFirmware})
