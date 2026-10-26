import subprocess
from pathlib import Path

JOTPLUGGLER_DIR = Path(__file__).parent
JOTPLUGGLER_BIN = JOTPLUGGLER_DIR / "jotpluggler"


def run_jotpluggler(*args):
  assert JOTPLUGGLER_BIN.exists(), "jotpluggler not built (scons -u iqpilot/tools/jotpluggler)"
  return subprocess.run([str(JOTPLUGGLER_BIN), *args], cwd=JOTPLUGGLER_DIR,
                        capture_output=True, text=True, timeout=60)


class TestJotpluggler:
  def test_help(self):
    result = run_jotpluggler("-h")
    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stderr

  def test_generated_dbcs_materialized(self):
    # the build materializes iqdbc's *_generated.dbc files; layout.cc and
    # sketch_layout.cc both resolve DBC names against this directory
    generated = JOTPLUGGLER_DIR / "generated_dbcs"
    assert generated.is_dir()
    assert list(generated.glob("*.dbc")), "no generated DBCs — iqdbc create_all did not run"

  def test_car_fingerprint_header_uses_iqdbc_platforms(self):
    header = (JOTPLUGGLER_DIR / "car_fingerprint_to_dbc.h").read_text()
    assert "kCarFingerprintToDbc" in header
    assert "dbc_for_car_fingerprint" in header

  def test_bootstrap_icons_vendored(self):
    # IQ.Pilot vendors the TTF because third_party/bootstrap is git-lfs; icons.cc
    # reads this exact path instead of upstream's BOOTSTRAP_ICONS_TTF define
    assert (JOTPLUGGLER_DIR / "assets" / "bootstrap-icons.ttf").is_file()

  def test_konn3kt_route_links(self):
    # iqpilot routes live on konn3kt; the useradmin buttons are gone
    common = (JOTPLUGGLER_DIR / "common.cc").read_text()
    assert '"https://konn3kt.com"' in common
    assert "useradmin.comma.ai" not in common
    assert "route_konn3kt_url" in common

  def test_route_files_go_through_konn3kt_api(self):
    # upstream calls PyDownloader::getRouteFiles here; iqpilot has no py_downloader
    sketch = (JOTPLUGGLER_DIR / "sketch_layout.cc").read_text()
    assert "PyDownloader::" not in sketch
    assert "py_downloader.h" not in sketch
    assert "CommaApi2::getRouteFiles" in sketch
