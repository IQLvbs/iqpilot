# Copyright (c) 2026 IQ.Lvbs LLC. All Rights Reserved.
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope='module')
def auth_runner(tmp_path_factory):
  root = tmp_path_factory.mktemp('cabana-auth-process')
  source = root / 'main.cc'
  source.write_text('''// Copyright (c) 2026 IQ.Lvbs LLC. All Rights Reserved.
#include "tools/cabana/ui/auth.h"
#include <chrono>
#include <iostream>
#include <thread>
int main(int argc, char **argv) {
  std::atomic<bool> abort = false;
  std::thread cancel;
  if (argc > 2) cancel = std::thread([&]() { std::this_thread::sleep_for(std::chrono::milliseconds(250)); abort = true; });
  const auto result = authenticateKonn3kt(argv[1], &abort);
  if (cancel.joinable()) cancel.join();
  std::cout << result;
}
''')
  binary = root / 'auth-runner'
  subprocess.run([
    'c++', '-std=c++17', '-pthread', '-I', str(ROOT / 'iqpilot'),
    f'-DCABANA_PYTHON="{sys.executable}"', f'-DCABANA_ROOT="{ROOT}"',
    str(source), str(ROOT / 'iqpilot/tools/cabana/ui/auth.cc'), '-o', str(binary),
  ], check=True, capture_output=True)
  return binary


@pytest.fixture
def auth_environment(tmp_path):
  class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
      assert self.path == '/v1/me'
      assert self.headers['Authorization'] == 'JWT process-test-token'
      self.send_response(200)
      self.send_header('Content-Type', 'application/json')
      self.end_headers()
      self.wfile.write(b'{"id":"test-user"}')

    def log_message(self, *args):
      pass

  server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
  worker = threading.Thread(target=server.serve_forever)
  worker.start()
  opener = tmp_path / ('open' if sys.platform == 'darwin' else 'xdg-open')
  opener.write_text(f'''#!{sys.executable}
# Copyright (c) 2026 IQ.Lvbs LLC. All Rights Reserved.
import os
import sys
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
from urllib.parse import urlencode
if not os.environ.get('TEST_AUTH_CANCEL'):
  callback = parse_qs(urlsplit(sys.argv[1]).query)['redirect'][0]
  state = parse_qs(urlsplit(callback).query)['state'][0]
  request = Request(callback, data=urlencode({{'state': state, 'token': 'process-test-token'}}).encode())
  urlopen(request, timeout=30).read()
''')
  opener.chmod(0o700)
  env = {**os.environ, 'HOME': str(tmp_path), 'PATH': f'{tmp_path}:{os.environ["PATH"]}',
         'API_HOST': f'http://127.0.0.1:{server.server_port}'}
  try:
    yield env, tmp_path
  finally:
    server.shutdown()
    worker.join()
    server.server_close()


# The runner and the fake browser cold-start from TMPDIR, which is a USB disk on the Mac mini CI runner.
AUTH_RUNNER_TIMEOUT_S = 60

@pytest.mark.parametrize('provider', ['google', 'github', 'apple', 'microsoft'])
def test_native_auth_completes_from_another_directory(auth_runner, auth_environment, provider):
  env, home = auth_environment
  result = subprocess.run([auth_runner, provider], cwd=home, env=env, capture_output=True, text=True, timeout=AUTH_RUNNER_TIMEOUT_S)
  assert result.returncode == 0, result.stderr
  assert json.loads(result.stdout) == {'success': True}, result.stderr
  assert json.loads((home / '.iq/auth.json').read_text()) == {'access_token': 'process-test-token'}


def test_native_auth_cancellation(auth_runner, auth_environment):
  env, home = auth_environment
  env['TEST_AUTH_CANCEL'] = '1'
  result = subprocess.run([auth_runner, 'google', 'cancel'], cwd=home, env=env, capture_output=True, text=True, timeout=AUTH_RUNNER_TIMEOUT_S)
  assert result.returncode == 0, result.stderr
  assert result.stdout == ''
  assert not (home / '.iq/auth.json').exists()
