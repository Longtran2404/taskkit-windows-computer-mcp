import threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from win10_bridge_mcp import recovery, server, viewer
from win10_bridge_mcp.policy import CaptureRegistry, Rect


@pytest.fixture(autouse=True)
def reset_recovery():
    recovery.reset()
    yield
    recovery.reset()


@pytest.fixture
def environment(monkeypatch):
    registry=CaptureRegistry()
    win=SimpleNamespace(id='w',hwnd=1,pid=1,title='Fixture',exe='python.exe',rect=Rect(0,0,100,100))
    native=SimpleNamespace(enumerate_windows=lambda _:[win],window_details=lambda *_:{},
                           get_window=lambda *_:win,capture_window=lambda _:(b'png','test',False))
    monkeypatch.setattr(server,'REGISTRY',registry)
    monkeypatch.setattr(server,'backend',lambda:native)
    monkeypatch.setattr(server,'load_config',lambda:{'allowed':{'python.exe'},'mouse_control_mode':'foreground_session'})
    return registry,win,native


def test_timeout_recovers_with_inspection_then_fresh_capture_without_restart(environment,monkeypatch):
    registry,win,native=environment
    old=registry.issue(win.id,win.rect,'old')
    recovery.pause('invoke','timeout')
    with pytest.raises(RuntimeError,match='Session is still active'):server.verify_capture(old.token,win.id,win.rect)
    # Capturing alone cannot acknowledge an uncertain application state.
    premature=server.capture_window(win.id)
    assert recovery.status()['recovery_required']
    forbidden=Mock(side_effect=AssertionError('Observation requested owner restart'))
    monkeypatch.setattr(server,'start_control_session',forbidden)
    assert server.inspect_windows()['windows'][0]['window_id']==win.id
    server.capture_window(win.id)
    assert not recovery.status()['recovery_required']
    assert not recovery.status()['requires_owner_restart']
    with pytest.raises(ValueError,match='Unknown'):server.verify_capture(old.token,win.id,win.rect)
    assert registry._tickets
    newest=max(registry._tickets.values(),key=lambda ticket:ticket.created)
    server.verify_capture(newest.token,win.id,win.rect)
    forbidden.assert_not_called()


def test_old_capture_rejected_even_when_clock_does_not_advance(environment,monkeypatch):
    from win10_bridge_mcp import policy
    monkeypatch.setattr(policy.time,'monotonic',lambda:123.0)
    registry,win,_=environment
    old=registry.issue(win.id,win.rect,'old')
    recovery.pause('invoke','timeout');server.inspect_windows();server.capture_window(win.id)
    assert not recovery.status()['recovery_required']
    with pytest.raises(ValueError,match='Unknown'):server.verify_capture(old.token,win.id,win.rect)
    fresh=next(iter(registry._tickets.values()))
    assert fresh.created==old.created
    server.verify_capture(fresh.token,win.id,win.rect)


def test_blank_or_failed_capture_cannot_recover(environment):
    registry,win,native=environment
    recovery.pause('invoke','timeout');server.inspect_windows()
    native.capture_window=lambda _:(b'png','test',True)
    with pytest.raises(RuntimeError,match='blank'):server.capture_window(win.id)
    assert recovery.status()['recovery_required'] and not registry._tickets


def test_inflight_observations_cannot_acknowledge_later_failure():
    before=recovery.observation()
    recovery.pause('invoke','timeout');recovery.inspected(before)
    assert not recovery.status()['windows_inspected']
    recovery.inspected(recovery.observation());before_capture=recovery.observation()
    recovery.pause('value','timeout');recovery.captured(before_capture)
    assert recovery.status()['recovery_required']


def test_desktop_screenshot_does_not_recover(environment,monkeypatch):
    from win10_bridge_mcp import desktop
    monkeypatch.setattr(server,'load_config',lambda:{'allowed':{'*'}})
    monkeypatch.setattr(desktop,'capture',lambda *_:(b'png',{}))
    recovery.pause('invoke','timeout');server.inspect_windows();server.capture_desktop()
    assert recovery.status()['recovery_required']


@pytest.mark.skipif(__import__('sys').platform!='win32',reason='Windows emergency stop')
def test_timeout_recovery_never_clears_owner_emergency_stop(environment,monkeypatch):
    from win10_bridge_mcp import windows_native as native
    stop=threading.Event();stop.set()
    monkeypatch.setattr(native,'SESSION_STOP',stop)
    monkeypatch.setattr(native.U,'GetAsyncKeyState',lambda _:0)
    recovery.pause('invoke','timeout');server.inspect_windows();server.capture_window('w')
    assert not recovery.status()['recovery_required'] and stop.is_set()
    with pytest.raises(InterruptedError):native._stop_if_needed()


def test_explicit_new_task_resets_timeout_gate(environment):
    registry,win,native=environment
    native.start_new_session=Mock()
    old=registry.issue(win.id,win.rect,'old')
    recovery.pause('invoke','timeout');assert server.start_control_session()['started']
    assert not recovery.status()['recovery_required']
    assert recovery.status()['last_uncertain_operation'] is None
    with pytest.raises(ValueError):registry.verify(old.token,win.id,win.rect)
