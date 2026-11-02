"""
Copyright © IQ.Lvbs, apart of Project Teal Lvbs, All Rights Reserved, licensed under https://konn3kt.com/tos
"""
import os
import subprocess
import sys

from iqpilot.common.basedir import BASEDIR


def _runtime_paths(env):
  result = subprocess.run(
    [
      sys.executable,
      "-c",
      "import os; import iqpilot.system.proprietary_runtime; print(os.environ['OPENPILOT_BASEDIR']); "
      + "print(os.environ['IQPILOT_PROPRIETARY_ROOT'])",
    ],
    env=env,
    check=True,
    capture_output=True,
    text=True,
  )
  return result.stdout.splitlines()


def test_basedir_contract():
  env = os.environ.copy()
  env.pop("OPENPILOT_BASEDIR", None)
  env.pop("IQPILOT_PROPRIETARY_ROOT", None)
  assert _runtime_paths(env) == [BASEDIR, os.path.join(BASEDIR, "artifacts")]


def test_explicit_basedir_is_preserved(tmp_path):
  env = os.environ.copy()
  env["OPENPILOT_BASEDIR"] = str(tmp_path)
  env["IQPILOT_PROPRIETARY_ROOT"] = str(tmp_path / "bundles")
  assert _runtime_paths(env) == [str(tmp_path), str(tmp_path / "bundles")]


def _bundle(root, name):
  path = root / name
  path.mkdir(parents=True)
  (path / "manifest.json").write_text("{}")
  return str(path)


def test_bundle_root_falls_back_to_the_tree_by_default(tmp_path, monkeypatch):
  from iqpilot.system.proprietary_runtime.bundle_modes import bundle_root
  tree = tmp_path / "tree"
  in_tree = _bundle(tree / "artifacts", "iqpilot_x_private")
  monkeypatch.setenv("IQPILOT_PROPRIETARY_ROOT", str(tmp_path / "store"))
  monkeypatch.delenv("IQPILOT_PROPRIETARY_STRICT", raising=False)
  assert bundle_root("iqpilot_x_private", str(tree)) == in_tree


def test_strict_bundle_root_never_falls_back_to_the_tree(tmp_path, monkeypatch):
  from iqpilot.system.proprietary_runtime.bundle_modes import bundle_root
  tree = tmp_path / "tree"
  _bundle(tree / "artifacts", "iqpilot_x_private")
  _bundle(tree / ".iqpilot" / "bundles", "iqpilot_x_private")
  stored = _bundle(tmp_path / "store", "iqpilot_y_private")
  monkeypatch.setenv("IQPILOT_PROPRIETARY_ROOT", str(tmp_path / "store"))
  monkeypatch.setenv("IQPILOT_PROPRIETARY_STRICT", "1")
  assert bundle_root("iqpilot_x_private", str(tree)) is None
  assert bundle_root("iqpilot_y_private", str(tree)) == stored
