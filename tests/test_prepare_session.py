import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from mcp.types import CallToolResult, TextContent, ImageContent
from win10_bridge_mcp import server, viewer, recovery


@pytest.fixture
def env(monkeypatch):
    native=SimpleNamespace(SESSION_STOP=threading.Event(),enable_session_stop=Mock(),_stop_if_needed=Mock())
    def start(): native.SESSION_STOP.clear()
    native.start_new_session=Mock(side_effect=start)
    monkeypatch.setattr(server,'backend',lambda:native)
    monkeypatch.setattr(server,'load_config',lambda:{'mouse_control_mode':'foreground_session','allowed':{'*'}})
    monkeypatch.setattr(viewer,'stopped',lambda:False)
    monkeypatch.setattr(server,'_session_end_reason',None)
    monkeypatch.setattr(server,'inspect_windows',Mock(return_value={'windows':[{'window_id':'w','blocked_by_window_id':None}]}))
    monkeypatch.setattr(server,'capture_window',Mock(return_value=CallToolResult(content=[
        TextContent(type='text',text=json.dumps({'capture_id':'fresh','window_id':'w'})),
        ImageContent(type='image',mimeType='image/png',data='cG5n')])) )
    monkeypatch.setattr(server,'REGISTRY',SimpleNamespace(invalidate_all=Mock()))
    monkeypatch.setattr(recovery,'reset',Mock())
    return native


def info(result): return json.loads(result.content[0].text)


@pytest.mark.parametrize('reason',['completed','handoff',None])
def test_owner_request_reopens_and_captures_without_confirmation(env,monkeypatch,reason):
    env.SESSION_STOP.set()
    monkeypatch.setattr(server,'_session_end_reason',reason)
    result=server.prepare_control_session('w',new_task=True)
    data=info(result)
    assert data['restarted'] and data['status']=='captured'
    assert not data['requires_owner_confirmation'] and not data['input_sent']
    assert data['capture']['capture_id']=='fresh' and result.content[1].type=='image'
    env.start_new_session.assert_called_once()
    server.REGISTRY.invalidate_all.assert_called_once()
    assert server._session_end_reason is None


def test_stopped_task_never_rearms_without_new_owner_request(env):
    env.SESSION_STOP.set()
    with pytest.raises(InterruptedError,match='without another question'):
        server.prepare_control_session('w')
    env.start_new_session.assert_not_called()
    server.inspect_windows.assert_not_called()
    server.capture_window.assert_not_called()


@pytest.mark.parametrize('new_task',[True,False])
def test_active_preparation_is_idempotent_and_preserves_recovery(env,new_task):
    for _ in range(2):
        assert not info(server.prepare_control_session('w',new_task=new_task))['restarted']
    env.start_new_session.assert_not_called()
    recovery.reset.assert_not_called()
    server.REGISTRY.invalidate_all.assert_not_called()


def test_missing_target_returns_inventory_without_capture_or_guessing(env):
    result=info(server.prepare_control_session('gone'))
    assert result['status']=='target_missing' and result['windows'][0]['window_id']=='w'
    server.capture_window.assert_not_called()


def test_no_target_returns_selection_without_fake_ready_ticket(env):
    result=info(server.prepare_control_session())
    assert result['status']=='select_target' and 'capture' not in result
    server.capture_window.assert_not_called()


def test_blocking_dialog_is_captured_without_confirming_it(env):
    server.inspect_windows.return_value={'windows':[{'window_id':'w','blocked_by_window_id':'dialog'}]}
    result=info(server.prepare_control_session('w'))
    assert result['target_window_id']=='dialog'
    server.capture_window.assert_called_once_with('dialog')


def test_disabled_mode_remains_disabled(env,monkeypatch):
    monkeypatch.setattr(server,'load_config',lambda:{'mouse_control_mode':'disabled'})
    with pytest.raises(PermissionError):server.prepare_control_session(new_task=True)
    env.enable_session_stop.assert_not_called()
    env.start_new_session.assert_not_called()


def test_held_emergency_key_still_refuses_reopening(env):
    env.SESSION_STOP.set()
    env.start_new_session.side_effect=InterruptedError('Release Esc/F12')
    with pytest.raises(InterruptedError,match='Release'):
        server.prepare_control_session('w',new_task=True)
    assert env.SESSION_STOP.is_set()
    server.capture_window.assert_not_called()


def test_finished_session_error_explains_no_question_recovery(env,monkeypatch):
    monkeypatch.setattr(server,'_session_end_reason','completed')
    env._stop_if_needed.side_effect=InterruptedError('stopped')
    with pytest.raises(InterruptedError,match='without asking again'):
        server.require_session({'mouse_control_mode':'foreground_session'})
    env.start_new_session.assert_not_called()


def test_new_stop_during_preparation_is_not_cleared(env):
    env._stop_if_needed.side_effect=InterruptedError('Esc')
    with pytest.raises(InterruptedError):server.prepare_control_session('w')
    env.start_new_session.assert_not_called()
    server.capture_window.assert_not_called()
