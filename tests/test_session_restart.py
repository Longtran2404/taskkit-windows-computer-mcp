import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from win10_bridge_mcp import server, viewer, indicator
from win10_bridge_mcp.policy import CaptureRegistry, Rect


def test_start_invalidates_old_tickets_and_requires_enabled_mode(monkeypatch):
    registry = CaptureRegistry()
    rect = Rect(0, 0, 100, 100)
    ticket = registry.issue('w', rect, 'test')
    native = SimpleNamespace(start_new_session=Mock())
    monkeypatch.setattr(server, 'REGISTRY', registry)
    monkeypatch.setattr(server, 'backend', lambda: native)
    monkeypatch.setattr(server, 'load_config', lambda: {'mouse_control_mode': 'disabled'})
    with pytest.raises(PermissionError):
        server.start_control_session()
    native.start_new_session.assert_not_called()
    registry.verify(ticket.token, 'w', rect)
    monkeypatch.setattr(server, 'load_config', lambda: {'mouse_control_mode': 'foreground_session'})
    assert server.start_control_session()['started']
    native.start_new_session.assert_called_once()
    with pytest.raises(ValueError, match='Unknown'):
        registry.verify(ticket.token, 'w', rect)


def test_read_only_tools_do_not_require_or_restart_input(monkeypatch):
    from win10_bridge_mcp import ui_access
    forbidden = Mock(side_effect=AssertionError('Read-only tool attempted to arm input'))
    monkeypatch.setattr(server, 'require_session', forbidden)
    monkeypatch.setattr(server, 'load_config', lambda: {'mouse_control_mode': 'foreground_session', 'allowed': {'notepad.exe'}})
    win = SimpleNamespace(id='w', hwnd=1, title='Test', exe='notepad.exe', pid=1, rect=Rect(0, 0, 100, 100))
    native = SimpleNamespace(enumerate_windows=lambda _: [win], get_window=lambda *_: win,
                             capture_window=lambda _: (b'png', 'test', False))
    monkeypatch.setattr(server, 'backend', lambda: native)
    monkeypatch.setattr(ui_access, 'inspect', lambda _: [])
    assert server.inspect_windows()['windows'][0]['window_id'] == 'w'
    assert server.inspect_controls('w')['controls'] == []
    assert server.capture_window('w').content[1].type == 'image'
    forbidden.assert_not_called()


@pytest.mark.skipif(sys.platform != 'win32', reason='Win32 session watcher')
def test_new_session_retires_old_event_and_repeated_stops(monkeypatch):
    from win10_bridge_mcp import windows_native as n
    monkeypatch.setattr(n.U, 'GetAsyncKeyState', lambda _: 0)
    monkeypatch.setattr(n, '_release_all', Mock())
    monkeypatch.setattr(viewer, 'reset_for_new_session', Mock())
    monkeypatch.setattr(viewer, 'stopped', lambda: False)
    monkeypatch.setattr(indicator, 'reset_for_new_session', Mock())
    for _ in range(3):
        old = n.SESSION_STOP
        old.set()
        with pytest.raises(InterruptedError):
            n._stop_if_needed()
        n.start_new_session()
        assert old.is_set() and n.SESSION_STOP is not old
        n._stop_if_needed()
    n.SESSION_STOP.set()
    n._session_watcher.join(1)


@pytest.mark.skipif(sys.platform != 'win32', reason='Win32 emergency key')
@pytest.mark.parametrize('key', [0x1B, 0x7B])
def test_restart_refuses_held_emergency_key(monkeypatch, key):
    from win10_bridge_mcp import windows_native as n
    monkeypatch.setattr(n.U, 'GetAsyncKeyState', lambda k: 0x8000 if k == key else 0)
    monkeypatch.setattr(n, '_release_all', Mock())
    monkeypatch.setattr(viewer, 'reset_for_new_session', Mock())
    monkeypatch.setattr(indicator, 'reset_for_new_session', Mock())
    with pytest.raises(InterruptedError, match='Release'):
        n.start_new_session()
    assert n.SESSION_STOP.is_set()


def test_reset_refuses_live_previous_preview(monkeypatch):
    process = SimpleNamespace(join=Mock(), is_alive=lambda: True)
    monkeypatch.setattr(viewer, '_process', process)
    with pytest.raises(RuntimeError, match='Previous preview'):
        viewer.reset_for_new_session()
    assert viewer.STOP.is_set()
    viewer.STOP.clear()
    viewer._closed.clear()


def test_reset_refuses_live_previous_indicator(monkeypatch):
    import threading
    monkeypatch.setattr(indicator, '_process', SimpleNamespace(join=Mock(), is_alive=lambda: True))
    monkeypatch.setattr(indicator, '_closed', threading.Event())
    with pytest.raises(RuntimeError, match='Previous indicator'):
        indicator.reset_for_new_session()
    assert indicator._closed.is_set()
