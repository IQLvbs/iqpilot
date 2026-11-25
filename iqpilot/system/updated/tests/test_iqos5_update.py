"""IQ.OS 4 -> 5 through alpha's updater: the build being left flashes and switches, before and after the reset."""
import subprocess
import types

import pytest

from iqpilot.common.params import Params
from iqpilot.system.updated import updated

IQOS5_ENV = 'export AGNOS_VERSION="IQ.OS 5.0.12"\nexport AGNOS_COMPAT_VERSIONS="IQ.OS 5.0.11"\n'
IQOS4_ENV = 'export AGNOS_VERSION="IQ.OS 4.9.9.4"\nexport AGNOS_COMPAT_VERSIONS=""\n'
MANIFEST = b'[{"name": "abl"}]\n'
SIGNATURE = b'c2lnbmF0dXJl\n'


def git(repo, *args):
  return subprocess.check_output(['git', '-c', 'commit.gpgsign=false', '-C', str(repo), *args],
                                 text=True, stderr=subprocess.STDOUT).strip()


def commit_release(remote, launch_env, message):
  (remote / 'launch_env.sh').write_text(launch_env)
  manifest = remote / 'iqpilot/system/hardware/tici/iqos.json'
  manifest.parent.mkdir(parents=True, exist_ok=True)
  manifest.write_bytes(MANIFEST)
  manifest.with_name('iqos.json.sig').write_bytes(SIGNATURE)
  git(remote, 'add', '.')
  git(remote, 'commit', '-qm', message)


@pytest.fixture(params=["IQ.OS 4.9.9.4", "IQ.OS 4.9.9.5"])
def agnos_device(tmp_path, monkeypatch, request):
  remote = tmp_path / 'remote'
  repo = tmp_path / 'checkout'
  remote.mkdir()
  git(remote, 'init', '-q', '-b', 'alpha')
  git(remote, 'config', 'user.name', 'Updater Test')
  git(remote, 'config', 'user.email', 'updater@example.invalid')
  commit_release(remote, IQOS4_ENV, 'IQ.OS 4 release')
  git(tmp_path, 'clone', '-q', str(remote), str(repo))
  params = Params(str(tmp_path / 'params'))
  monkeypatch.setattr(updated, 'BASEDIR', str(repo))
  monkeypatch.setattr(updated, 'Params', lambda: params)
  monkeypatch.setattr(updated, 'AGNOS', True)
  monkeypatch.setattr(updated, 'configure_git_auth', lambda _cwd: None)
  monkeypatch.setattr(updated, 'set_offroad_alert', lambda *_args: None)
  monkeypatch.setattr(updated.HARDWARE, 'get_os_version', lambda: request.param)
  monkeypatch.setattr(updated, 'handle_agnos_update', lambda: pytest.fail('the new tree must not flash'))

  events = []

  def flash_for(commit, basedir, current, target, compat, version_allowed, _log, _alert, _agnos):
    if not target.startswith('IQ.OS 5') or current.startswith('IQ.OS 5') or version_allowed(current, target, compat):
      return None
    manifest_bytes = subprocess.check_output(['git', 'show', f'{commit}:iqpilot/system/hardware/tici/iqos.json'], cwd=basedir)
    signature_bytes = subprocess.check_output(['git', 'show', f'{commit}:iqpilot/system/hardware/tici/iqos.json.sig'], cwd=basedir)
    events.append(('flash', 0, manifest_bytes, signature_bytes, git(repo, 'rev-parse', 'HEAD')))
    return 0

  def switch_slot(slot, _log):
    events.append(('switch', slot, git(repo, 'rev-parse', 'HEAD')))

  module = types.SimpleNamespace(flash_for=flash_for, switch_slot=switch_slot)
  monkeypatch.setattr(updated, 'iqos5_module', lambda: module)
  return remote, repo, updated.Updater(), events, module


def test_flashes_before_the_checkout_changes_and_switches_after(agnos_device):
  remote, repo, updater, events, module = agnos_device
  old_head = git(repo, 'rev-parse', 'HEAD')
  commit_release(remote, IQOS5_ENV, 'IQ.OS 5 release')
  new_head = git(remote, 'rev-parse', 'HEAD')

  updater.fetch_update()

  assert events == [('flash', 0, MANIFEST, SIGNATURE, old_head), ('switch', 0, new_head)]
  assert git(repo, 'rev-parse', 'HEAD') == new_head
  assert updater.os_flashed


def test_failed_switch_restores_the_previous_checkout(agnos_device, monkeypatch):
  remote, repo, updater, events, module = agnos_device
  old_head = git(repo, 'rev-parse', 'HEAD')
  commit_release(remote, IQOS5_ENV, 'IQ.OS 5 release')

  def refuse(_slot, _log):
    raise Exception('switching to slot 0 failed')

  monkeypatch.setattr(module, 'switch_slot', refuse)
  with pytest.raises(Exception, match='switching to slot 0 failed'):
    updater.fetch_update()

  assert git(repo, 'rev-parse', 'HEAD') == old_head
  assert git(repo, 'symbolic-ref', '--short', 'HEAD') == 'alpha'
  assert not updater.os_flashed


def test_failed_flash_leaves_the_checkout_alone(agnos_device, monkeypatch):
  remote, repo, updater, events, module = agnos_device
  old_head = git(repo, 'rev-parse', 'HEAD')
  commit_release(remote, IQOS5_ENV, 'IQ.OS 5 release')

  def fail(*_args):
    raise Exception('download failed')

  monkeypatch.setattr(module, 'flash_for', fail)
  with pytest.raises(Exception, match='download failed'):
    updater.fetch_update()

  assert git(repo, 'rev-parse', 'HEAD') == old_head
  assert git(repo, 'for-each-ref', 'refs/iqos/checkpoint') == ''


@pytest.mark.parametrize('current', ['IQ.OS 5.0.11', 'IQ.OS 5.0.12'])
def test_iqos5_device_is_left_to_the_existing_path(agnos_device, monkeypatch, current):
  remote, repo, updater, events, module = agnos_device
  commit_release(remote, IQOS5_ENV, 'IQ.OS 5 release')
  monkeypatch.setattr(updated.HARDWARE, 'get_os_version', lambda: current)
  monkeypatch.setattr(updated, 'handle_agnos_update', lambda: False)

  updater.fetch_update()

  assert events == []
  assert git(repo, 'rev-parse', 'HEAD') == git(remote, 'rev-parse', 'HEAD')


def test_iqos4_release_keeps_the_agnos_path(agnos_device, monkeypatch):
  remote, repo, updater, events, module = agnos_device
  commit_release(remote, IQOS4_ENV.replace('4.9.9.4', '4.9.9.5'), 'IQ.OS 4 update')
  calls = []
  monkeypatch.setattr(updated, 'handle_agnos_update', lambda: calls.append(git(repo, 'rev-parse', 'HEAD')) or True)

  updater.fetch_update()

  assert events == []
  assert calls == [git(remote, 'rev-parse', 'HEAD')]
  assert updater.os_flashed


@pytest.mark.parametrize('current,expected,compat,allowed', [
  ('IQ.OS 4.9.9.6', 'IQ.OS 4.9.9.6', [], True),
  ('4.9.9.7', 'IQ.OS 4.9.9.7', [], True),
  ('IQ.OS 4.9.9.7', '4.9.9.7', [], True),
  ('4.9.9.7-dev', '4.9.9.7', [], True),
  ('5.0.11', 'IQ.OS 5.0.12', ['IQ.OS 5.0.11'], True),
  ('IQ.OS 4.9.9.6', '4.9.9.7', [], False),
  ('16.1', 'IQ.OS 4.9.9.7', [], False),
])
def test_version_allowed_ignores_iqos_prefix(current, expected, compat, allowed):
  assert updated.agnos_version_allowed(current, expected, compat) == allowed


def test_missing_bundle_skips_the_move_before_the_checkout_changes(agnos_device, monkeypatch):
  remote, repo, updater, events, module = agnos_device
  old_head = git(repo, 'rev-parse', 'HEAD')
  commit_release(remote, IQOS5_ENV, 'IQ.OS 5 release')
  monkeypatch.setattr(updated, 'iqos5_module', lambda: None)

  with pytest.raises(updated.IQOS5ModuleUnavailable):
    updater.fetch_update()

  assert events == []
  assert git(repo, 'rev-parse', 'HEAD') == old_head
  assert git(repo, 'for-each-ref', 'refs/iqos/checkpoint') == ''
  assert not updater.os_flashed


def test_missing_bundle_does_not_block_an_iqos4_release(agnos_device, monkeypatch):
  remote, repo, updater, events, module = agnos_device
  commit_release(remote, IQOS4_ENV.replace('4.9.9.4', '4.9.9.5'), 'IQ.OS 4 update')
  monkeypatch.setattr(updated, 'iqos5_module', lambda: None)
  monkeypatch.setattr(updated, 'handle_agnos_update', lambda: True)

  updater.fetch_update()

  assert git(repo, 'rev-parse', 'HEAD') == git(remote, 'rev-parse', 'HEAD')
  assert updater.os_flashed


def test_unverifiable_bundle_counts_as_missing(monkeypatch):
  from iqpilot.system.proprietary_runtime import bundle_modes

  def refuse(_bundle, _module):
    raise ImportError('signature mismatch')

  monkeypatch.setattr(bundle_modes, 'import_verified_module', refuse)
  assert updated.iqos5_module() is None
