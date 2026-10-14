import pytest
import threading
from win10_bridge_mcp import server, viewer
from win10_bridge_mcp.policy import CaptureRegistry
from win10_bridge_mcp.consent import ConsentGate
from win10_bridge_mcp.permissions import PermissionRuntime
from fakes import FakeBackend


@pytest.fixture(autouse=True)
def isolate_process_state(monkeypatch):
    viewer.STOP.clear()
    viewer._closed.clear()
    monkeypatch.setattr(viewer, '_process', None)
    monkeypatch.setattr(viewer, '_starting_event', None)
    monkeypatch.setattr(viewer, '_owner_stop', threading.Event())
    monkeypatch.setattr(viewer, '_owner_stops', [])
    monkeypatch.setattr(server, 'PERMISSIONS', PermissionRuntime())
    monkeypatch.setattr(server, 'REGISTRY', CaptureRegistry())
    monkeypatch.setattr(server, 'CONSENT', ConsentGate())
    monkeypatch.setattr(server, 'APP_CONSENT', ConsentGate('semantic_control_mode'))
    monkeypatch.setattr(server, 'CAPTURE_CONSENT', ConsentGate('capture_consent_mode'))
    yield
    viewer.STOP.clear()
    viewer._closed.clear()


@pytest.fixture
def bridge(monkeypatch):
    native = FakeBackend()
    cfg = {'allowed': frozenset({'notepad.exe'}), 'mouse_control_mode': 'foreground_session',
           'semantic_control_mode': 'disabled', 'capture_modes': ['window'],
           'capture_consent_mode': 'session'}
    monkeypatch.setattr(server, 'backend', lambda: native)
    monkeypatch.setattr(server, 'load_config', lambda: cfg)
    monkeypatch.setattr(server, 'ask_local_consent', lambda _: True)
    return native, cfg


@pytest.fixture
def ticket(bridge):
    native, _ = bridge
    win = native.current
    return server.REGISTRY.issue(win.id, win.rect, 'fake', dpi=win.dpi).token
