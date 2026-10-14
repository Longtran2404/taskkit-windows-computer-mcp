import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from win10_bridge_mcp import server, viewer


def test_authorized_session_config(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"allow_processes": ["notepad.exe", "explorer.exe"],
                             "mouse_control_mode": "foreground_session"}))
    monkeypatch.setenv("WIN10_BRIDGE_CONFIG", str(p))
    assert server.load_config()["mouse_control_mode"] == "foreground_session"


def test_key_rejects_system_chords(monkeypatch):
    monkeypatch.setattr(server, "load_config", lambda: {})
    monkeypatch.setattr(server, "backend", lambda: SimpleNamespace(KEY_CODES={"ctrl": 17, "s": 83}))
    with pytest.raises(ValueError):
        server.press_key("w", "token", "win+r")


def test_text_rejects_control_characters():
    with pytest.raises(ValueError):
        server.type_text("w", "token", "hello\x00world")


def test_semantic_save_preserves_differing_file(monkeypatch, tmp_path):
    from win10_bridge_mcp import ui_access
    p = tmp_path / "test.txt"
    p.write_text("Keep original", encoding="utf-8")
    win = SimpleNamespace(exe="notepad.exe", hwnd=1, rect=None)
    native = SimpleNamespace(get_window=lambda *_: win)
    monkeypatch.setattr(server, "load_config", lambda: {"allowed": {"notepad.exe"}})
    monkeypatch.setattr(server, "backend", lambda: native)
    monkeypatch.setattr(server.REGISTRY, "verify", lambda *_: None)
    monkeypatch.setattr(server.REGISTRY, "consume", lambda *_: None)
    monkeypatch.setattr(server, "require_session", lambda *_: native)
    monkeypatch.setattr(ui_access, "value", lambda *_: "New text")
    with pytest.raises(FileExistsError):
        server.save_notepad_text("w", "token", str(p), False, False)
    assert p.read_text() == "Keep original"


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 input backend")
def test_unicode_input_and_focus_abort_release(monkeypatch):
    from win10_bridge_mcp import windows_native as native
    win = SimpleNamespace(hwnd=1)
    viewer.STOP.clear(); viewer._closed.clear(); native.SESSION_STOP.clear()
    monkeypatch.setattr(native, "_activate", lambda *_: None)
    monkeypatch.setattr(native.U, "GetForegroundWindow", lambda: 1)
    monkeypatch.setattr(native.U, "GetAsyncKeyState", lambda _: 0)
    sent = []
    monkeypatch.setattr(native, "_send", lambda inp: sent.append((inp.payload.ki.wScan, inp.payload.ki.dwFlags)))
    release = Mock()
    monkeypatch.setattr(native, "_release_all", release)
    native.apply_text(win, "ệ")
    assert sent == [(ord("ệ"), 4), (ord("ệ"), 6)]
    release.assert_called_once()
    monkeypatch.setattr(native.U, "GetForegroundWindow", lambda: 2)
    with pytest.raises(RuntimeError):
        native.apply_text(win, "never")
    assert release.call_count == 2


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 input backend")
def test_escape_latch_survives_key_release(monkeypatch):
    from win10_bridge_mcp import windows_native as native
    viewer.STOP.clear(); viewer._closed.clear(); native.SESSION_STOP.clear()
    monkeypatch.setattr(native.U, "GetAsyncKeyState", lambda key: 1 if key == 0x1B else 0)
    with pytest.raises(InterruptedError):
        native._stop_if_needed()
    monkeypatch.setattr(native.U, "GetAsyncKeyState", lambda _: 0)
    with pytest.raises(InterruptedError):
        native._stop_if_needed()
    native.SESSION_STOP.clear()
