"""
Copyright © IQ.Lvbs, part of Project Teal Lvbs, All Rights Reserved, licensed under https://iqlvbs.com/terms
"""
import subprocess
import sys

from iqpilot.system.ui.lib.updater_output import drain_stderr, failure_reason

CHATTY_UPDATER = """
import sys
for i in range(20000):
  print('IQ.OS proxy: retrying image fetch ' + str(i), file=sys.stderr, flush=True)
print('Downloading:5', flush=True)
print('Error: konn3kt registration failed for a15da42415bc1323: HTTP 401', flush=True)
sys.exit(1)
"""


def run_updater(script: str) -> tuple[int, str, str]:
  with subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1) as proc:
    tail = drain_stderr(proc)
    error = ""
    for line in proc.stdout:
      if line.startswith("Error:"):
        error = line[len("Error:"):].strip()
    code = proc.wait(timeout=30)
    tail.thread.join(timeout=30)
  return code, error, failure_reason(error, tail)


def test_a_chatty_updater_cannot_block_on_stderr_and_its_error_is_kept():
  code, _, reason = run_updater(CHATTY_UPDATER)
  assert code == 1
  assert reason == "konn3kt registration failed for a15da42415bc1323: HTTP 401"


def test_the_last_stderr_line_explains_a_failure_without_an_error_line():
  code, error, reason = run_updater("import sys; print('boom: disk full', file=sys.stderr); sys.exit(2)")
  assert (code, error, reason) == (2, "", "boom: disk full")
