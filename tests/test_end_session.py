import threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from win10_bridge_mcp import server, viewer, indicator
from win10_bridge_mcp.policy import CaptureRegistry, Rect


@pytest.fixture
def environment(monkeypatch):
    native=SimpleNamespace(SESSION_STOP=threading.Event(),release_all=Mock(),start_new_session=Mock())
    registry=CaptureRegistry()
    ticket=registry.issue('w',Rect(0,0,100,100),'before completion')
    monkeypatch.setattr(server,'backend',lambda:native)
    monkeypatch.setattr(server,'REGISTRY',registry)
    monkeypatch.setattr(server,'_session_end_reason',None)
    monkeypatch.setattr(viewer,'close_viewer',Mock())
    monkeypatch.setattr(viewer,'wait_closed',Mock(return_value=True))
    monkeypatch.setattr(indicator,'close',Mock(return_value=True))
    return native,registry,ticket


@pytest.mark.parametrize('reason',['completed','handoff'])
def test_finish_stops_input_invalidates_captures_and_closes_overlays(environment,reason):
    native,registry,ticket=environment
    result=server.end_control_session(reason)
    assert native.SESSION_STOP.is_set()
    assert result['ended'] and result['preview_closed'] and result['indicator_closed']
    assert result['applications_left_open'] and result['mcp_connected']
    assert server._session_end_reason==reason
    with pytest.raises(ValueError,match='Unknown'):registry.verify(ticket.token,'w',ticket.rect)
    viewer.close_viewer.assert_called_once();viewer.wait_closed.assert_called_once()
    indicator.close.assert_called_once()
    native.start_new_session.assert_not_called()


def test_stop_signal_precedes_input_mutex_wait(environment,monkeypatch):
    native,_,_=environment
    class InputLock:
        def __enter__(self):
            assert native.SESSION_STOP.is_set()
            native.release_all.assert_called()
        def __exit__(self,*args):pass
    monkeypatch.setattr(server,'MOUSE_MUTEX',InputLock())
    server.end_control_session()


def test_finish_is_idempotent_and_does_not_require_working_config(environment,monkeypatch):
    native,_,_=environment
    monkeypatch.setattr(server,'load_config',Mock(side_effect=AssertionError('Cleanup read config')))
    assert server.end_control_session()['ended']
    assert server.end_control_session()['ended']
    assert native.SESSION_STOP.is_set()


def test_incomplete_gui_cleanup_does_not_claim_completion_or_rearm(environment,monkeypatch):
    native,registry,ticket=environment
    monkeypatch.setattr(viewer,'wait_closed',lambda:False)
    with pytest.raises(RuntimeError,match='has not exited'):server.end_control_session()
    assert native.SESSION_STOP.is_set()
    assert ticket.token not in registry._tickets
    indicator.close.assert_called_once()
    native.start_new_session.assert_not_called()


def test_invalid_finish_reason_has_no_effect(environment):
    native,registry,ticket=environment
    with pytest.raises(ValueError):server.end_control_session('restart')
    assert not native.SESSION_STOP.is_set()
    native.release_all.assert_not_called();viewer.close_viewer.assert_not_called()
    registry.verify(ticket.token,'w',ticket.rect)


def test_new_owner_task_clears_completion_status(environment,monkeypatch):
    native,registry,_=environment
    server.end_control_session()
    monkeypatch.setattr(server,'load_config',lambda:{'mouse_control_mode':'foreground_session'})
    def start():native.SESSION_STOP=threading.Event()
    native.start_new_session.side_effect=start
    assert server.start_control_session()['started']
    assert server._session_end_reason is None and not native.SESSION_STOP.is_set()
