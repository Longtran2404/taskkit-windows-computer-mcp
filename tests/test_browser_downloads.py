import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from win10_bridge_mcp import downloads, server
from win10_bridge_mcp.policy import Rect


@pytest.fixture
def registry():
    now = [0.0]
    return downloads.DownloadRegistry(lambda: now[0]), now


def test_rename_partial_then_stable(registry, tmp_path):
    r, now = registry
    token = r.prepare(str(tmp_path), 'result.txt')
    partial = tmp_path / 'result.txt.crdownload'
    partial.write_bytes(b'hello')
    assert r.status(token)['status'] == 'in_progress'
    partial.rename(tmp_path / 'result.txt')
    assert r.status(token)['status'] == 'settling'
    now[0] = 1.1
    result = r.status(token)
    assert result['status'] == 'file_observed'
    assert result['files'][0]['size_bytes'] == 5
    assert result['source_verified'] is False


def test_changing_disappearing_and_zero_byte_files(registry, tmp_path):
    r, now = registry
    token = r.prepare(str(tmp_path))
    file = tmp_path / 'a.txt'
    file.touch()
    r.status(token)
    now[0] = 2
    file.write_bytes(b'changed')
    assert r.status(token)['status'] == 'settling'
    file.unlink()
    assert r.status(token)['status'] == 'waiting'
    file.touch()
    r.status(token)
    now[0] = 4
    assert r.status(token)['status'] == 'file_observed'


def test_existing_file_never_counts_as_download_and_replacement_needs_review(registry, tmp_path):
    r, now = registry
    file = tmp_path / 'old.txt'
    file.write_text('old')
    token = r.prepare(str(tmp_path))
    assert r.status(token)['status'] == 'waiting'
    file.write_text('replacement')
    assert r.status(token)['status'] == 'needs_review'
    with pytest.raises(ValueError, match='already exists'):
        r.prepare(str(tmp_path), 'old.txt')


def test_multiple_and_unrelated_partial_require_review(registry, tmp_path):
    r, now = registry
    token = r.prepare(str(tmp_path))
    (tmp_path / 'a').touch()
    (tmp_path / 'b').touch()
    assert r.status(token)['status'] == 'needs_review'
    (tmp_path / 'b.crdownload').touch()
    assert r.status(token)['status'] == 'in_progress'


def test_expected_filter_and_expiry(registry, tmp_path):
    r, now = registry
    token = r.prepare(str(tmp_path), 'expected.txt')
    (tmp_path / 'unrelated').touch()
    assert r.status(token)['files'] == []
    now[0] = 3600
    with pytest.raises(ValueError, match='expired'):
        r.status(token)


@pytest.mark.parametrize('name', ['../x', 'a/b', 'a\\b', '..', '*.txt', 'a:b'])
def test_invalid_names_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        downloads.DownloadRegistry().prepare(str(tmp_path), name)


@pytest.mark.parametrize('path', ['relative', '//server/share', '\\\\server\\share'])
def test_nonlocal_directory_rejected(path):
    with pytest.raises(ValueError):
        downloads.directory(path)


def test_symlinks_not_followed(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    secret = target / 'secret'
    secret.touch()
    link = tmp_path / 'link'
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip('Symlink privilege unavailable')
    assert 'link' not in downloads.snapshot(tmp_path)


@pytest.fixture
def browser(monkeypatch, tmp_path):
    native = SimpleNamespace(get_window=Mock(return_value=SimpleNamespace(exe='chrome.exe', rect=Rect(0, 0, 400, 400))), _activate=Mock())
    monkeypatch.setattr(server, 'load_config', lambda: {'allowed': {'*'}})
    monkeypatch.setattr(server, 'require_session', Mock(return_value=native))
    invoke = Mock(return_value={'dry_run': True, 'target_rect': [20, 20, 100, 50]})
    monkeypatch.setattr(server, 'app_control', invoke)
    monkeypatch.setattr(server, 'click_left', Mock(return_value={'performed': True}))
    monkeypatch.setattr(downloads, 'REGISTRY', downloads.DownloadRegistry())
    return native, invoke


@pytest.mark.parametrize('exe', ['chrome.exe', 'msedge.exe'])
def test_both_browsers_invoke_exactly_once(browser, tmp_path, exe):
    native, invoke = browser
    native.get_window.return_value.exe = exe
    result = server.browser_download('window', 'capture', str(tmp_path), control_name='Tải xuống', dry_run=False)
    assert result['status'] == 'waiting'
    assert result['invocation'] == 'requested'
    assert invoke.call_count == 1
    server.click_left.assert_called_once_with('window', 'capture', 60, 35, dry_run=False)
    server.browser_download_status(result['download_id'])
    assert invoke.call_count == 1


def test_dry_run_never_starts_download_or_retains_receipt(browser, tmp_path):
    native, invoke = browser
    assert server.browser_download('w', 'c', str(tmp_path), control_name='Download')['dry_run']
    assert invoke.call_count == 1
    assert not downloads.REGISTRY.jobs


def test_uncertain_invoke_has_receipt_and_no_retry(browser, tmp_path):
    native, invoke = browser
    server.click_left.side_effect = TimeoutError('unknown outcome')
    result = server.browser_download('w', 'c', str(tmp_path), control_name='Download', dry_run=False)
    assert result['status'] == 'action_uncertain'
    assert server.browser_download_status(result['download_id'])['invocation'] == 'uncertain'
    assert invoke.call_count == 1


def test_reject_nonbrowser_before_invoke(browser, tmp_path):
    native, invoke = browser
    native.get_window.return_value.exe = 'notepad.exe'
    with pytest.raises(ValueError, match='only'):
        server.browser_download('w', 'c', str(tmp_path), control_name='Download', dry_run=False)
    invoke.assert_not_called()


def test_stopped_session_prevents_snapshot_or_click(browser, tmp_path, monkeypatch):
    native, invoke = browser
    monkeypatch.setattr(server, 'require_session', Mock(side_effect=RuntimeError('Stopped')))
    with pytest.raises(RuntimeError, match='Stopped'):
        server.browser_download('w', 'c', str(tmp_path), control_name='Download', dry_run=False)
    invoke.assert_not_called()
    assert not downloads.REGISTRY.jobs


def test_bad_capture_or_ambiguous_control_prevents_receipt(browser, tmp_path):
    native, invoke = browser
    invoke.side_effect = ValueError('Unknown capture or ambiguous button')
    with pytest.raises(ValueError):
        server.browser_download('w', 'c', str(tmp_path), control_name='Download', dry_run=False)
    assert not downloads.REGISTRY.jobs


def test_metadata_reads_never_rearm_or_touch_backend(browser, tmp_path, monkeypatch):
    token = downloads.REGISTRY.prepare(str(tmp_path))
    backend = Mock(side_effect=AssertionError('No native access'))
    monkeypatch.setattr(server, 'backend', backend)
    assert server.browser_download_status(token)['status'] == 'waiting'
    backend.assert_not_called()

def test_existing_name_case_collision_refused(registry, tmp_path):
    r, now = registry
    (tmp_path / 'REPORT.PDF').touch()
    with pytest.raises(ValueError, match='already exists'):
        r.prepare(str(tmp_path), 'report.pdf')


def test_capacity_and_expiry_cleanup(registry, tmp_path):
    r, now = registry
    for _ in range(32):
        r.prepare(str(tmp_path))
    with pytest.raises(ValueError, match='capacity'):
        r.prepare(str(tmp_path))
    now[0] = 3600
    r.prepare(str(tmp_path))
    assert len(r.jobs) == 1


def test_hidden_or_offwindow_button_never_clicked(browser, tmp_path):
    native, inspect = browser
    inspect.return_value['target_rect'] = [0, 0, 0, 0]
    with pytest.raises(ValueError, match='visible bounds'):
        server.browser_download('w', 'c', str(tmp_path), control_name='Download', dry_run=False)
    server.click_left.assert_not_called()
    inspect.return_value['target_rect'] = [500, 500, 600, 600]
    with pytest.raises(ValueError, match='outside window'):
        server.browser_download('w', 'c', str(tmp_path), control_name='Download', dry_run=False)
    server.click_left.assert_not_called()

def test_directory_disappears_preserves_receipt(registry, tmp_path):
    r, now = registry
    folder = tmp_path / 'download'
    folder.mkdir()
    token = r.prepare(str(folder))
    r.invocation(token, 'requested')
    folder.rmdir()
    result = r.status(token)
    assert result['download_id'] == token
    assert result['status'] == 'observation_error'
    assert result['invocation'] == 'requested'
