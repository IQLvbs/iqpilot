import json
import subprocess
from pathlib import Path


CABANA_DIR = Path(__file__).parent
CABANA_BIN = CABANA_DIR / "_cabana"


def read(name):
  return (CABANA_DIR / name).read_text()


class TestCabanaBinary:
  def test_help(self):
    assert CABANA_BIN.exists(), "cabana not built (scons -u iqpilot/tools/cabana/_cabana)"
    result = subprocess.run([str(CABANA_BIN), "--help"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stderr
    assert "--zmq" in result.stderr
    assert "--bridge" in result.stderr

  def test_launcher_builds_current_targets(self):
    launcher = read("cabana")
    assert "iqpilot/tools/cabana/_cabana" in launcher
    assert "iqpilot/cereal/messaging/bridge" in launcher
    assert "openpilot/tools/cabana" not in launcher


class TestKonn3ktIntegration:
  def test_routes_use_konn3kt_api(self):
    routes = read("routes.cc")
    assert "PyDownloader::" not in routes
    assert "py_downloader.h" not in routes
    assert "CommaApi2::getDevices()" in routes
    assert "CommaApi2::getDeviceRoutes(" in routes

  def test_no_comma_endpoints(self):
    for name in ("routes.cc", "ui/main.cc", "README.md"):
      body = read(name)
      assert "api.comma.ai" not in body, name

  def test_dbc_menu_uses_iqdbc(self):
    mainwin = read("ui/mainwin.cc")
    assert "IQ.Pilot iqdbc" in mainwin
    assert "commaai/opendbc" not in mainwin

  def test_dbc_json_generator_imports_iqdbc(self):
    generator = read("dbc/generate_dbc_json.py")
    assert "from iqdbc.car" in generator
    assert "from opendbc.car" not in generator

  def test_generated_dbc_json_covers_iqdbc_platforms(self):
    path = CABANA_DIR / "dbc" / "car_fingerprint_to_dbc.json"
    assert path.is_file(), "run scons -u iqpilot/tools/cabana/_cabana"
    mapping = json.loads(path.read_text())
    assert len(mapping) > 100
    assert all(isinstance(value, str) and value for value in mapping.values())

  def test_canproxy_targets_konn3kt(self):
    proxy = read("konn3kt_canproxy.py")
    assert "konn3kt" in proxy
    assert 'os.environ["ZMQ"] = "1"' in proxy


class TestDeviceStreamModes:
  def test_three_modes_exist(self):
    header = read("streams/devicestream.h")
    assert "enum class Mode { Msgq, Zmq, Bridge };" in header

  def test_only_zmq_mode_talks_zmq(self):
    source = read("streams/devicestream.cc")
    assert 'mode_ == Mode::Zmq ? setenv("ZMQ", "1", 1) : unsetenv("ZMQ")' in source

  def test_zmq_mode_uses_requested_address(self):
    source = read("streams/devicestream.cc")
    assert 'const std::string socket_address = mode_ == Mode::Zmq ? address_ : "127.0.0.1";' in source

  def test_only_bridge_mode_forks_bridge(self):
    source = read("streams/devicestream.cc")
    assert "if (mode_ == Mode::Bridge) {" in source


class TestFrontendRemoval:
  def test_qt_frontend_is_absent(self):
    assert not (CABANA_DIR / "cabana.cc").exists()
    assert not (CABANA_DIR / "mainwin.cc").exists()

  def test_imgui_frontend_is_present(self):
    assert (CABANA_DIR / "ui" / "app.cc").is_file()
    assert (CABANA_DIR / "ui" / "main.cc").is_file()

  def test_stream_selector_stays_in_main_window(self):
    app = read("ui/app.cc")
    assert "io.ConfigFlags |= ImGuiConfigFlags_ViewportsEnable" not in app


class TestReplayVideo:
  def test_iqpilot_camera_index_services_are_replayed(self):
    source = read("streams/replaystream.cc")
    for service in ("roadEncodeIdx", "driverEncodeIdx", "wideRoadEncodeIdx"):
      assert f'"{service}"' in source
    assert '"narrowRoadEncodeIdx"' not in source
    assert '"cabinEncodeIdx"' not in source
