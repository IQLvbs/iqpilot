import subprocess
from pathlib import Path

CABANA_DIR = Path(__file__).parent.parent


class TestCabanaUi:
  def test_help(self):
    result = subprocess.run(["./_cabana", "-h"], cwd=CABANA_DIR, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "Usage:" in result.stderr
