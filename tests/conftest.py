import pytest
from win10_bridge_mcp import server, viewer
from win10_bridge_mcp.policy import CaptureRegistry
from win10_bridge_mcp.consent import ConsentGate
from fakes import FakeBackend


@pytest.fixture(autouse=True)
def isolate_process_state(monkeypatch):
    viewer.STOP.clear()
    viewer._closed.clear()
    monkeypatch.setattr(viewer, '_process', None)
    monkeypatch.setattr(server, 'REGISTRY', CaptureRegistry())
    monkeypatch.setattr(server, 'CONSENT', ConsentGate())
    yield
    viewer.STOP.clear()
    viewer._closed.clear()


@pytest.fixture
def bridge(monkeypatch):
    native = FakeBackend()
    cfg = {'allowed': frozenset({'notepad.exe'}), 'mouse_control_mode': 'foreground_session'}
    monkeypatch.setattr(server, 'backend', lambda: native)
    monkeypatch.setattr(server, 'load_config', lambda: cfg)
    monkeypatch.setattr(server, 'ask_local_consent', lambda _: True)
    return native, cfg


@pytest.fixture
def ticket(bridge):
    native, _ = bridge
    win = native.current
    return server.REGISTRY.issue(win.id, win.rect, 'fake', dpi=win.dpi).token
