import json
import sys
from types import SimpleNamespace

import pytest
from win10_bridge_mcp.policy import normalize_allowlist, process_allowed
from win10_bridge_mcp import server


def test_explicit_all_applications_and_new_names():
    allowed = normalize_allowlist(['*'])
    assert allowed == {'*'}
    assert process_allowed('NewApplication.exe', allowed)
    assert process_allowed('Ứng dụng mới.exe', allowed)
    assert not process_allowed(None, allowed)
    assert not process_allowed('', allowed)
    assert not process_allowed('unknown.exe', normalize_allowlist(['notepad']))


@pytest.mark.parametrize('value', [['*.exe'], ['*', 'notepad.exe'], '*'])
def test_wildcard_must_be_explicit_entire_scope(value):
    with pytest.raises(ValueError):
        normalize_allowlist(value)


def test_all_apps_does_not_enable_input(monkeypatch, tmp_path):
    config = tmp_path/'all.json'
    config.write_text(json.dumps({'allow_processes': ['*']}))
    monkeypatch.setenv('WIN10_BRIDGE_CONFIG', str(config))
    assert server.load_config()['allowed'] == {'*'}
    assert server.load_config()['mouse_control_mode'] == 'disabled'


def test_open_directory_accepts_owner_all_apps_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(server, 'load_config', lambda: {'allowed': {'*'}, 'mouse_control_mode': 'foreground_session'})
    calls = []
    monkeypatch.setattr(server, 'backend', lambda: SimpleNamespace(enable_session_stop=lambda: None, _stop_if_needed=lambda: None))
    monkeypatch.setattr(server.os, 'startfile', lambda path: calls.append(path), raising=False)
    assert server.open_directory(str(tmp_path))['open_requested']
    assert calls == [str(tmp_path.resolve())]


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows enumeration')
def test_native_enumeration_uses_scope_for_new_app(monkeypatch):
    from win10_bridge_mcp import windows_native as n
    monkeypatch.setattr(n.U, 'IsWindowVisible', lambda _: True)
    monkeypatch.setattr(n.U, 'IsIconic', lambda _: False)
    monkeypatch.setattr(n.U, 'GetWindowThreadProcessId', lambda *_: 1)
    monkeypatch.setattr(n, 'executable', lambda _: 'newly-opened-app.exe')
    def rect(_, value):
        value = n.ct.cast(value, n.ct.POINTER(n.RECT))
        value.contents.left, value.contents.top, value.contents.right, value.contents.bottom = 0, 0, 500, 400
        return True
    monkeypatch.setattr(n.U, 'GetWindowRect', rect)
    monkeypatch.setattr(n.U, 'GetWindowTextLengthW', lambda _: 4)
    def title(_, buf, __):
        buf.value = 'Test'
        return 4
    monkeypatch.setattr(n.U, 'GetWindowTextW', title)
    monkeypatch.setattr(n.U, 'EnumWindows', lambda cb, _: cb(123, 0))
    assert n.enumerate_windows(frozenset({'notepad.exe'})) == []
    assert n.enumerate_windows(frozenset({'*'}))[0].exe == 'newly-opened-app.exe'
