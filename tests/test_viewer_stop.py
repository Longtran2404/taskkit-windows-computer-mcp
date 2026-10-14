import sys
from unittest.mock import Mock
import pytest
from win10_bridge_mcp import viewer


@pytest.fixture(autouse=True)
def clear_stop():
    viewer.STOP.clear()
    viewer._closed.clear()
    if sys.platform == "win32":
        from win10_bridge_mcp import windows_native as native
        native.SESSION_STOP.clear()
    yield
    viewer.STOP.clear()
    viewer._closed.clear()
    if sys.platform == "win32":
        native.SESSION_STOP.clear()


def test_close_latches_stop():
    viewer.STOP.clear()
    viewer.close_viewer()
    assert viewer.STOP.is_set()
    assert viewer._closed.is_set()
    viewer.STOP.clear()


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 backend")
def test_escape_and_latch_interrupt(monkeypatch):
    from win10_bridge_mcp import windows_native as native
    viewer.STOP.clear()
    monkeypatch.setattr(native.U, "GetAsyncKeyState", lambda key: 0x8000 if key == 0x1B else 0)
    with pytest.raises(InterruptedError):
        native._stop_if_needed()
    monkeypatch.setattr(native.U, "GetAsyncKeyState", lambda key: 0)
    viewer.close_viewer()
    with pytest.raises(InterruptedError):
        native._stop_if_needed()
    viewer.STOP.clear()


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 backend")
def test_abort_drag_releases_buttons(monkeypatch):
    from win10_bridge_mcp import windows_native as native
    from win10_bridge_mcp.policy import Rect
    viewer.STOP.clear()
    win = native.Window(1, 1, "notepad.exe", "Test", Rect(0, 0, 500, 500))
    monkeypatch.setattr(native, "_activate", lambda _: None)
    monkeypatch.setattr(native, "_position", lambda *_: None)
    monkeypatch.setattr(native, "_verify_hit", lambda *_: None)
    monkeypatch.setattr(native.U, "GetAsyncKeyState", lambda _: 0)
    monkeypatch.setattr(native.U, "GetForegroundWindow", lambda: 1)
    sent = []
    def mouse(flags, data):
        sent.append(flags)
        if flags == native.MOUSE_LEFT_DOWN:
            viewer.close_viewer()
    monkeypatch.setattr(native, "_mouse", mouse)
    release = Mock()
    monkeypatch.setattr(native, "_release_all", release)
    with pytest.raises(InterruptedError):
        native.apply_mouse(win, "drag", "left", 50, 50, 100, 100, 6000, 2, 1, "vertical", ())
    assert native.MOUSE_LEFT_DOWN in sent
    release.assert_called_once()
    viewer.STOP.clear()
