import json
import sys
import pytest
from win10_bridge_mcp import server


def test_authorized_session_config(monkeypatch, tmp_path):
    p = tmp_path / 'config.json'
    p.write_text(json.dumps({'allow_processes': ['notepad.exe', 'explorer.exe'],
                             'mouse_control_mode': 'foreground_session'}))
    monkeypatch.setenv('WIN10_BRIDGE_CONFIG', str(p))
    assert server.load_config()['mouse_control_mode'] == 'foreground_session'
    assert not server.CONSENT.armed(server.load_config())


def test_key_rejects_system_chords(bridge):
    with pytest.raises(ValueError):
        server.press_key('w', 'token', 'win+r')


def test_text_rejects_control_characters():
    with pytest.raises(ValueError):
        server.type_text('w', 'token', 'hello\x00world')


@pytest.mark.skipif(sys.platform != 'win32', reason='Actual Win32 ABI only; no input injected')
def test_native_input_abi():
    import ctypes
    from win10_bridge_mcp import windows_native as n
    assert ctypes.sizeof(n.INPUT) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)
    assert ctypes.sizeof(n.POINT) == 8
    assert n.NativeAdapter().code('key', 17) == {17, 162, 163}


@pytest.mark.skipif(sys.platform != 'win32', reason='Win32 key-state adapter simulated')
def test_escape_latch_survives_key_release(monkeypatch):
    from win10_bridge_mcp import windows_native as native
    native.SESSION_STOP.clear()
    monkeypatch.setattr(native.U, 'GetAsyncKeyState', lambda key: 1 if key == 0x1B else 0)
    with pytest.raises(InterruptedError): native._stop_if_needed()
    monkeypatch.setattr(native.U, 'GetAsyncKeyState', lambda _: 0)
    with pytest.raises(InterruptedError): native._stop_if_needed()
    native.SESSION_STOP.clear()  # test teardown only; no production clear path
