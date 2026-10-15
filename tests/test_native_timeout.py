import json
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from win10_bridge_mcp import native_worker as worker, server, recovery


@pytest.fixture(autouse=True)
def reset_recovery():
    recovery.reset()
    yield
    recovery.reset()


class BlockedProcess:
    pid = 999
    returncode = None
    def __init__(self):
        self.killed = False
        self.communications = 0
    def communicate(self, input=None, timeout=None):
        self.communications += 1
        if self.killed:
            return b'', b''
        raise subprocess.TimeoutExpired('fixture', timeout)
    def poll(self):
        return self.returncode
    def kill(self):
        self.killed = True
        self.returncode = -1


def test_read_timeout_kills_worker_without_latching_or_retry(monkeypatch):
    process = BlockedProcess()
    start = Mock(return_value=process)
    monkeypatch.setattr(worker.subprocess, 'Popen', start)
    with pytest.raises(TimeoutError, match='No input was sent'):
        worker.call('inspect', {'hwnd': 1}, timeout=.01)
    start.assert_called_once()
    assert process.killed
    assert worker.status()['active_operations'] == []
    assert worker.status()['last_failure']['result_unknown'] is False


@pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows cancellation')
def test_mutation_timeout_requires_observation_without_stopping_or_replay(monkeypatch):
    from win10_bridge_mcp import windows_native as native
    stop = threading.Event()
    release = Mock()
    monkeypatch.setattr(native, 'SESSION_STOP', stop)
    monkeypatch.setattr(native, '_stop_if_needed', lambda: None)
    monkeypatch.setattr(native, 'release_all', release)
    process = BlockedProcess(); start = Mock(return_value=process)
    monkeypatch.setattr(worker.subprocess, 'Popen', start)
    with pytest.raises(TimeoutError, match='Result unknown'):
        worker.call('invoke', {'hwnd': 1}, mutating=True, timeout=.01)
    assert not stop.is_set() and process.killed
    assert recovery.status()['recovery_required']
    start.assert_called_once(); release.assert_called_once()
    assert worker.status()['last_failure']['result_unknown'] is True


@pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows cancellation')
def test_worker_exit_requires_observation_without_emergency_latch(monkeypatch):
    from win10_bridge_mcp import windows_native as native
    stop=threading.Event()
    monkeypatch.setattr(native,'SESSION_STOP',stop)
    monkeypatch.setattr(native,'_stop_if_needed',lambda:None)
    process=SimpleNamespace(pid=999,returncode=2,poll=lambda:2,communicate=lambda **kw:(b'',b''))
    monkeypatch.setattr(worker.subprocess,'Popen',lambda *a,**kw:process)
    with pytest.raises(RuntimeError,match='inspect_windows'):worker.call('invoke',{'hwnd':1},mutating=True)
    assert not stop.is_set() and recovery.status()['recovery_required']


@pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows cancellation')
def test_cancel_during_mutation_kills_worker(monkeypatch):
    from win10_bridge_mcp import windows_native as native
    process = BlockedProcess()
    checks = iter([None, InterruptedError('Cancelled')])
    def check():
        error = next(checks)
        if error: raise error
    monkeypatch.setattr(native, '_stop_if_needed', check)
    monkeypatch.setattr(worker.subprocess, 'Popen', lambda *a, **k: process)
    with pytest.raises(InterruptedError): worker.call('invoke', {'hwnd': 1}, mutating=True)
    assert process.killed and not worker.status()['active_operations']


def test_capture_timeout_issues_no_input_ticket(monkeypatch):
    native = SimpleNamespace(get_window=lambda *a: SimpleNamespace(rect=None),
                             capture_window=Mock(side_effect=TimeoutError('fixture')))
    monkeypatch.setattr(server, 'backend', lambda: native)
    monkeypatch.setattr(server, 'load_config', lambda: {'allowed': {'*'}})
    issue = Mock();monkeypatch.setattr(server.REGISTRY, 'issue', issue)
    with pytest.raises(TimeoutError): server.capture_window('w')
    issue.assert_not_called()


def test_worker_preserves_validation_errors_and_import_paths(monkeypatch):
    process = SimpleNamespace(pid=999, returncode=0, poll=lambda: 0,
                              communicate=lambda **kwargs: (json.dumps({'ok':False,'type':'ValueError','error':'Choose one control'}).encode(), b''))
    start = Mock(return_value=process)
    monkeypatch.setattr(worker.subprocess, 'Popen', start)
    with pytest.raises(ValueError, match='Choose one control'): worker.call('inspect', {'hwnd':1})
    assert start.call_args.args[0][1] == '-c'
    assert 'run_module' in start.call_args.args[0][2]


def test_worker_rejects_unknown_operations_before_start(monkeypatch):
    start = Mock();monkeypatch.setattr(worker.subprocess, 'Popen', start)
    with pytest.raises(ValueError): worker.call('shell', {})
    start.assert_not_called()


def test_transport_status_remains_responsive_during_native_wait(monkeypatch):
    import asyncio
    from win10_bridge_mcp import ui_access
    entered, release = threading.Event(), threading.Event()
    def blocked(_):
        entered.set()
        assert release.wait(2)
        return []
    monkeypatch.setattr(server,'backend',lambda:SimpleNamespace(get_window=lambda *a:SimpleNamespace(hwnd=1)))
    monkeypatch.setattr(server,'load_config',lambda:{'allowed':{'python.exe'},'mouse_control_mode':'disabled'})
    monkeypatch.setattr(ui_access,'inspect',blocked)
    async def exercise():
        pending=asyncio.create_task(server.mcp._tool_manager.get_tool('inspect_controls').fn(window_id='w'))
        try:
            assert await asyncio.to_thread(entered.wait,1)
            status=await asyncio.wait_for(server.mcp._tool_manager.get_tool('bridge_status').fn(),.5)
            assert status['mouse_mode']=='disabled' and not pending.done()
        finally:release.set()
        assert (await pending)['controls']==[]
    asyncio.run(exercise())
