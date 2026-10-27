"""Offline update release/download/install handoff invariants. Never installs software."""
import hashlib
import io
import json
import ctypes
import os
from pathlib import Path
import threading
import time

import pytest

from edakit.services import updates as u
from edakit.services import update_install as helper


PAYLOAD = b'MZ' + b'installer fixture' * 100


def release(number='9.0.0', **changes):
    tag = 'v' + number
    name = 'EdaKit-' + number + '-Setup.exe'
    data = {'tag_name': tag, 'draft': False, 'prerelease': False,
            'body': '<script>notes are plain text</script>', 'assets': [
                {'name': name, 'state': 'uploaded', 'size': len(PAYLOAD),
                 'browser_download_url': u.REPO + '/releases/download/' + tag + '/' + name,
                 'digest': 'sha256:' + hashlib.sha256(PAYLOAD).hexdigest()}]}
    data.update(changes)
    return data


class Response(io.BytesIO):
    def geturl(self):
        return 'https://release-assets.githubusercontent.com/test'


def prepared(tmp_path, monkeypatch):
    manager = u.Updater(tmp_path / 'updates')
    monkeypatch.setattr(u, 'read_url', lambda *a, **kw: json.dumps(release()).encode())
    manager._check()
    monkeypatch.setattr(u, 'open_url', lambda url: Response(PAYLOAD))
    return manager


def test_version_comparison():
    assert u.version('v0.1.10') > u.version('0.1.9')
    for bad in ('0.1.3rc1', '../../x', '1.2', None, '0.01.2'):
        with pytest.raises(ValueError):
            u.version(bad)


@pytest.mark.parametrize('url', ['http://github.com/a', 'https://example.org/a',
                                'file:///tmp/a', 'https://github.com:444/a',
                                'https://x:secret@github.com/a'])
def test_download_hosts_are_fixed(url):
    with pytest.raises(ValueError):
        u.allowed_url(url)


@pytest.mark.parametrize('change', [{'draft': True}, {'prerelease': True}, {'assets': []}])
def test_invalid_releases(change):
    with pytest.raises(ValueError):
        u.release_info(release(**change))


def test_asset_path_and_digest_validation():
    data = release()
    data['assets'][0]['browser_download_url'] = 'https://github.com/other/repo/setup.exe'
    with pytest.raises(ValueError):
        u.release_info(data)
    data = release()
    data['assets'][0].pop('digest')
    with pytest.raises(ValueError, match='SHA-256'):
        u.release_info(data)


def test_checksum_manifest_fallback(monkeypatch):
    data = release()
    data['assets'][0].pop('digest')
    data['assets'].append({'name': 'SHA256SUMS.txt', 'state': 'uploaded',
                          'browser_download_url': u.REPO + '/releases/download/v9.0.0/SHA256SUMS.txt'})
    digest = hashlib.sha256(PAYLOAD).hexdigest()
    monkeypatch.setattr(u, 'read_url', lambda *a: (digest + '  EdaKit-9.0.0-Setup.exe\n').encode())
    assert u.checksum_for(u.release_info(data)) == digest
    monkeypatch.setattr(u, 'read_url', lambda *a: b'no match')
    with pytest.raises(ValueError):
        u.checksum_for(u.release_info(data))


def test_check_current_does_not_downgrade(tmp_path, monkeypatch):
    manager = u.Updater(tmp_path)
    monkeypatch.setattr(u, 'read_url', lambda *a: json.dumps(release('0.1.0')).encode())
    manager._check()
    assert manager.snapshot()['phase'] == 'current'
    with pytest.raises(ValueError):
        manager.download()


def test_verified_download_and_plan_tamper(tmp_path, monkeypatch):
    manager = prepared(tmp_path, monkeypatch)
    manager._download()
    assert manager.snapshot()['phase'] == 'ready'
    path = Path(manager.package['path'])
    assert path.read_bytes() == PAYLOAD
    assert not list(manager.directory.rglob('*.part'))
    restored = u.Updater(manager.directory)
    assert restored.snapshot()['phase'] == 'ready'
    assert restored.package == manager.package
    root, cadence = tmp_path / 'installed', tmp_path / 'cadence'
    root.mkdir(); (root / 'deployment.ini').write_text('record')
    (cadence / 'tools/capture/tclscripts').mkdir(parents=True)
    plan = {**manager.package, 'root': str(root), 'cadence': str(cadence), 'scope': 'allusers'}
    manifest = path.parent / 'plan.json'
    manifest.write_text(json.dumps(plan))
    assert helper.load_plan(manifest)['version'] == '9.0.0'
    path.write_bytes(b'MZtampered')
    with pytest.raises(ValueError, match='SHA-256'):
        helper.load_plan(manifest)


@pytest.mark.parametrize('mode', ['truncated', 'oversized', 'hash', 'cancelled', 'not-exe'])
def test_download_failure_never_produces_installable_package(tmp_path, monkeypatch, mode):
    manager = prepared(tmp_path, monkeypatch)
    payload = PAYLOAD
    if mode == 'truncated': payload = PAYLOAD[:10]
    if mode == 'oversized': payload += b'x'
    if mode == 'hash': payload = b'xx' + PAYLOAD[2:]
    if mode == 'cancelled': manager.cancelled.set()
    if mode == 'not-exe':
        payload = b'xx' + PAYLOAD[2:]
        manager.data['release']['sha256'] = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(u, 'open_url', lambda *a: Response(payload))
    with pytest.raises(ValueError):
        manager._download()
    assert manager.package is None
    assert not list(manager.directory.rglob('*.part'))
    assert not list(manager.directory.rglob('*.exe'))


def test_settings_and_auto_failure_state(tmp_path, monkeypatch):
    manager = u.Updater(tmp_path)
    manager.command({'action': 'settings', 'autoCheck': False})
    monkeypatch.setattr(manager, 'start', lambda *a: pytest.fail('Disabled auto started'))
    manager.auto()
    assert not u.Updater(tmp_path).snapshot()['autoCheck']
    manager = u.Updater(tmp_path / 'failed')
    monkeypatch.setattr(u, 'read_url', lambda *a: (_ for _ in ()).throw(OSError('offline')))
    manager.start('check')
    until = time.monotonic() + 2
    while manager.active and time.monotonic() < until:
        time.sleep(.01)
    assert manager.snapshot()['phase'] == 'error'
    assert manager.snapshot()['message'] == 'offline'
    assert manager.snapshot()['lastChecked'] == 0


def test_single_task_and_source_install_refusal(tmp_path, monkeypatch):
    manager = prepared(tmp_path, monkeypatch)
    manager.active = True
    with pytest.raises(ValueError): manager.start('check')
    manager.active = False
    manager._download()
    monkeypatch.setattr(u.sys, 'frozen', False, raising=False)
    with pytest.raises(ValueError, match='Windows'):
        manager.install()


def test_waits_for_cad_and_old_service_then_two_clear_scans(tmp_path):
    scans = iter([['Capture.exe'], ['edakit.exe'], [], []])
    reports = []
    assert helper.wait_for_exit(tmp_path, threading.Event(), reports.append,
                                enumerate_processes=lambda root: next(scans), interval=0)
    assert 'Capture.exe' in reports[0] and 'edakit.exe' in reports[1]


def test_wait_cancellation_and_timeout(tmp_path):
    event = threading.Event(); event.set()
    assert not helper.wait_for_exit(tmp_path, event, lambda t: None,
                                     enumerate_processes=lambda r: pytest.fail('Cancelled'))
    clock = iter([0, 1, 2, 3])
    with pytest.raises(TimeoutError):
        helper.wait_for_exit(tmp_path, threading.Event(), lambda t: None,
                             enumerate_processes=lambda r: ['Capture.exe'],
                             interval=0, timeout=1, clock=lambda: next(clock))


def test_install_handoff_outside_target_and_cancel_retry(tmp_path, monkeypatch):
    manager = prepared(tmp_path, monkeypatch)
    manager._download()
    root = tmp_path / 'installed'
    root.mkdir()
    (root / 'edakit-cli.exe').write_bytes(b'MZhelper')
    monkeypatch.setattr(u, 'installation', lambda: (root, 'C:/Cadence', 'allusers'))
    calls = []
    class Child:
        done = False
        def poll(self): return 0 if self.done else None
    monkeypatch.setattr(u.subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, raising=False)
    monkeypatch.setattr(u.subprocess, 'CREATE_NO_WINDOW', 134217728, raising=False)
    monkeypatch.setattr(u.subprocess, 'Popen', lambda args, **kw: calls.append((args, kw)) or Child())
    assert manager.install()['phase'] == 'waiting'
    args, options = calls[0]
    assert Path(args[0]).parent != root
    assert args[1] == 'update-install'
    assert options['close_fds']
    assert options['env']['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
    manifest = json.loads((manager.helper / 'plan.json').read_text())
    assert manifest['root'] == str(root) and manifest['sha256'] == manager.package['sha256']
    (manager.helper / 'result.json').write_text(json.dumps({'phase': 'cancelled', 'message': 'cancelled'}))
    assert manager.snapshot()['phase'] == 'ready'
    assert manager.helper is None
    with pytest.raises(ValueError, match='旧更新助手'):
        manager.install()
    manager.helper_process.done = True
    manager.install()
    assert not (manager.helper / 'result.json').exists()  # No old cancellation replay.


def test_helper_start_failure_does_not_leave_waiting_forever(tmp_path, monkeypatch):
    manager = prepared(tmp_path, monkeypatch)
    manager._download()
    manager.helper = Path(manager.package['path']).parent
    class Failed:
        def poll(self): return 1
    manager.helper_process = Failed()
    manager.data['phase'] = 'waiting'
    assert manager.snapshot()['phase'] == 'ready'
    assert manager.helper is None


def test_corrupt_settings_do_not_break_startup(tmp_path):
    (tmp_path / 'settings.json').write_text(json.dumps({'autoCheck': 'false', 'lastAttempt': 'bad', 'lastChecked': []}))
    manager = u.Updater(tmp_path)
    assert manager.snapshot()['autoCheck'] is True
    assert manager.snapshot()['lastChecked'] == 0


@pytest.mark.parametrize('failure', ['', 'elevation', 'installer', 'version'])
@pytest.mark.parametrize('scope', ['allusers', 'currentuser'])
def test_windows_installer_handoff_and_completion_failures(tmp_path, monkeypatch, failure, scope):
    # Exercise the real ctypes call construction with fake OS functions, never UAC.
    calls = []
    class Function:
        def __init__(self, call): self.call = call
        def __call__(self, *args): return self.call(*args)
    class API: pass
    kernel, shell = API(), API()
    kernel.GetDllDirectoryW = Function(lambda *a: 0)
    kernel.SetDllDirectoryW = Function(lambda path: calls.append(('dll', path)) or 1)
    kernel.WaitForSingleObject = Function(lambda *a: 0)
    def exit_code(handle, code):
        code._obj.value = 1 if failure == 'installer' else 0
        return 1
    kernel.GetExitCodeProcess = Function(exit_code)
    kernel.CloseHandle = Function(lambda handle: calls.append(('close', handle)))
    def execute(ptr):
        info = ptr._obj
        assert info.verb == ('runas' if scope == 'allusers' else 'open')
        assert ('/ALLUSERS' if scope == 'allusers' else '/CURRENTUSER') in info.parameters
        assert '/DIR=' in info.parameters and '/CADENCEROOT=' in info.parameters
        assert '/SILENT' not in info.parameters
        info.process = 123
        calls.append(('execute', info.file))
        return failure != 'elevation'
    shell.ShellExecuteExW = Function(execute)
    monkeypatch.setattr(ctypes, 'WinDLL', lambda name, **kw: shell if name == 'shell32' else kernel, raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: 1223, raising=False)
    monkeypatch.setattr(helper.subprocess, 'CREATE_NO_WINDOW', 134217728, raising=False)
    monkeypatch.setattr(helper.subprocess, 'check_output', lambda *a, **kw: b'0.1.0' if failure == 'version' else b'9.0.0')
    plan = {'root': str(tmp_path / 'installed'), 'path': str(tmp_path / 'setup.exe'),
            'cadence': 'C:/Cadence Root', 'version': '9.0.0', 'scope': scope}
    if failure:
        with pytest.raises((OSError, ValueError)):
            helper._launch_setup(plan, tmp_path / 'install.log')
    else:
        helper._launch_setup(plan, tmp_path / 'install.log')
    assert ('execute', plan['path']) in calls
    assert sum(item[0] == 'dll' for item in calls) == 2
    assert any(item[0] == 'close' for item in calls) == (failure != 'elevation')


@pytest.mark.skipif(os.name != 'nt', reason='Windows native assistant lease')
def test_native_assistant_lease_excludes_duplicates_and_releases(tmp_path):
    with helper.assistant_lock(tmp_path):
        with pytest.raises(ValueError, match='已有更新助手'):
            with helper.assistant_lock(tmp_path):
                pytest.fail('Duplicate assistant acquired lease')
        with helper.assistant_lock(tmp_path / 'other'):
            pass
    with helper.assistant_lock(tmp_path):
        pass
