# Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms

import os
from pathlib import Path
import subprocess


IQ_COMMAND = Path(__file__).parents[1] / "iq.sh"


def make_checkout(tmp_path: Path) -> Path:
  checkout = tmp_path / "checkout"
  (checkout / "iqpilot").mkdir(parents=True)
  (checkout / "launch_iqpilot.sh").touch()
  return checkout


def run_pkg(checkout: Path, path: Path) -> subprocess.CompletedProcess[str]:
  env = os.environ.copy()
  env["PATH"] = f"{path}:{env['PATH']}"
  return subprocess.run(
    ["bash", str(IQ_COMMAND), "--dir", str(checkout), "pkg"],
    check=False,
    capture_output=True,
    env=env,
    text=True,
  )


def run_iq(checkout: Path, command: str, *args: str) -> subprocess.CompletedProcess[str]:
  return subprocess.run(
    ["bash", str(IQ_COMMAND), "--dir", str(checkout), command, *args],
    check=False,
    capture_output=True,
    text=True,
  )


def test_public_checkout_skips_private_package_source_setup(tmp_path: Path):
  checkout = make_checkout(tmp_path)

  result = run_pkg(checkout, tmp_path)

  assert result.returncode == 0
  assert "private package sources are not present" in result.stdout
  assert "setup_private_packages.py" not in result.stderr


def test_internal_checkout_runs_private_package_source_setup(tmp_path: Path):
  checkout = make_checkout(tmp_path)
  setup_script = checkout / "iqpilot/tools/scripts/setup_private_packages.py"
  setup_script.parent.mkdir(parents=True)
  setup_script.touch()
  python_log = tmp_path / "python.log"
  python = tmp_path / "python3"
  python.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" > {python_log!s}\n")
  python.chmod(0o755)

  result = run_pkg(checkout, tmp_path)

  assert result.returncode == 0
  assert python_log.read_text().strip() == "iqpilot/tools/scripts/setup_private_packages.py"


def test_public_checkout_runs_bundled_package_installer(tmp_path: Path):
  checkout = make_checkout(tmp_path)
  installer_log = tmp_path / "installer.log"
  installer = checkout / "artifacts/runtime/ensure_private_installed.sh"
  installer.parent.mkdir(parents=True)
  installer.write_text(f"printf installed > {installer_log!s}\n")

  result = run_pkg(checkout, tmp_path)

  assert result.returncode == 0
  assert installer_log.read_text() == "installed"


def test_cabana_command_runs_launcher_from_checkout(tmp_path: Path):
  checkout = make_checkout(tmp_path)
  log = tmp_path / "cabana.log"
  launcher = checkout / "iqpilot/tools/cabana/cabana"
  launcher.parent.mkdir(parents=True)
  launcher.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' \"$PWD|$*\" > {log!s}\n")
  launcher.chmod(0o755)

  result = run_iq(checkout, "cabana", "--msgq")

  assert result.returncode == 0
  assert log.read_text().strip() == f"{checkout}|--msgq"


def test_juggle_command_runs_launcher_from_checkout(tmp_path: Path):
  checkout = make_checkout(tmp_path)
  log = tmp_path / "juggle.log"
  launcher = checkout / "iqpilot/tools/jotpluggler/pluggle.py"
  launcher.parent.mkdir(parents=True)
  launcher.write_text(f"#!/usr/bin/env bash\nprintf '%s\\n' \"$PWD|$*\" > {log!s}\n")
  launcher.chmod(0o755)

  result = run_iq(checkout, "juggle", "route")

  assert result.returncode == 0
  assert log.read_text().strip() == f"{checkout}|route"


GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd: Path, *args: str) -> str:
  return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=GIT_ENV).stdout.strip()


def publish_prebuilt(remote: Path, branch: str, version: str) -> str:
  work = remote.parent / f"publish-{branch}-{version}"
  git(remote.parent, "init", "-q", "-b", branch, str(work))
  (work / "iqpilot").mkdir()
  (work / "iqpilot/__init__.py").touch()
  (work / "launch_iqpilot.sh").touch()
  (work / "VERSION").write_text(version)
  git(work, "add", "-A")
  git(work, "commit", "-q", "-m", f"IQ.Pilot Prebuilt Release {version}")
  git(work, "push", "-q", "--force", str(remote), f"HEAD:refs/heads/{branch}")
  return git(work, "rev-parse", "HEAD")


def make_device(tmp_path: Path) -> tuple[Path, Path]:
  remote = tmp_path / "remote.git"
  git(tmp_path, "init", "-q", "--bare", str(remote))
  publish_prebuilt(remote, "release", "1")
  publish_prebuilt(remote, "beta", "1")
  device = tmp_path / "openpilot"
  git(tmp_path, "clone", "-q", "--depth=1", "-b", "release", remote.as_uri(), str(device))
  git(device, "config", "--replace-all", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
  return remote, device


def run_update(device: Path) -> subprocess.CompletedProcess[str]:
  return subprocess.run(["bash", str(IQ_COMMAND), "--dir", str(device), "update"], check=False, capture_output=True, text=True, env=GIT_ENV)


def test_update_moves_to_a_republished_prebuilt(tmp_path: Path):
  remote, device = make_device(tmp_path)
  release = publish_prebuilt(remote, "release", "2")

  result = run_update(device)

  assert result.returncode == 0, result.stderr
  assert git(device, "rev-parse", "HEAD") == release
  assert (device / "VERSION").read_text() == "2"


def test_update_that_is_already_current_succeeds(tmp_path: Path):
  _, device = make_device(tmp_path)

  result = run_update(device)

  assert result.returncode == 0, result.stderr
  assert "already up to date" in result.stdout


def test_update_fetches_only_the_checked_out_branch(tmp_path: Path):
  remote, device = make_device(tmp_path)
  publish_prebuilt(remote, "beta", "2")
  release = publish_prebuilt(remote, "release", "2")

  result = run_update(device)

  assert result.returncode == 0, result.stderr
  assert git(device, "rev-parse", "HEAD") == release
  assert git(device, "for-each-ref", "refs/remotes/origin/beta") == ""


def test_update_moves_after_an_earlier_pull_fetched_but_could_not_merge(tmp_path: Path):
  remote, device = make_device(tmp_path)
  release = publish_prebuilt(remote, "release", "2")
  git(device, "fetch", "-q", "origin")

  result = run_update(device)

  assert result.returncode == 0, result.stderr
  assert git(device, "rev-parse", "HEAD") == release


def test_update_fast_forwards_a_branch_with_shared_history(tmp_path: Path):
  remote, device = make_device(tmp_path)
  work = tmp_path / "dev"
  git(tmp_path, "clone", "-q", "-b", "release", remote.as_uri(), str(work))
  (work / "VERSION").write_text("1.1")
  git(work, "commit", "-q", "-am", "next")
  git(work, "push", "-q", "origin", "release")

  result = run_update(device)

  assert result.returncode == 0, result.stderr
  assert git(device, "rev-parse", "HEAD") == git(work, "rev-parse", "HEAD")


def test_update_keeps_local_changes_when_the_branch_was_republished(tmp_path: Path):
  remote, device = make_device(tmp_path)
  before = git(device, "rev-parse", "HEAD")
  publish_prebuilt(remote, "release", "2")
  (device / "VERSION").write_text("mine")

  result = run_update(device)

  assert result.returncode == 1
  assert "iq switch release" in result.stderr
  assert git(device, "rev-parse", "HEAD") == before
  assert (device / "VERSION").read_text() == "mine"


def test_update_keeps_local_commits_when_the_branch_was_republished(tmp_path: Path):
  remote, device = make_device(tmp_path)
  (device / "VERSION").write_text("mine")
  git(device, "commit", "-q", "-am", "local work")
  mine = git(device, "rev-parse", "HEAD")
  publish_prebuilt(remote, "release", "2")

  result = run_update(device)

  assert result.returncode == 1
  assert git(device, "rev-parse", "HEAD") == mine


def test_desktop_tool_missing_from_host_checkout_fails(tmp_path: Path):
  checkout = make_checkout(tmp_path)

  result = run_iq(checkout, "cabana")

  assert result.returncode == 1
  assert "launcher is missing" in result.stderr
