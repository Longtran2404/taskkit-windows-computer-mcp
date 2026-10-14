import multiprocessing
import os
from pathlib import Path
import time
import pytest
from win10_bridge_mcp.bounded_worker import run


def worker(payload, cancel):
    mode, marker = payload
    if marker: Path(marker).write_text('started')
    if mode == 'hang':
        while True: time.sleep(.02)
    if mode == 'crash': os._exit(17)
    if mode == 'late': time.sleep(10)
    if mode == 'error': raise ValueError('bad native target')
    if mode == 'large': return b'x'*2_000_000
    return {'ok': True, 'bytes': b'png bytes'}


def test_success_and_native_error():
    assert run(worker, ('ok', None), timeout=3)['bytes'] == b'png bytes'
    with pytest.raises(ValueError, match='bad native target'):
        run(worker, ('error', None), timeout=3)


@pytest.mark.parametrize('mode', ['hang', 'late', 'crash'])
def test_timeout_crash_late_result_reaped(mode, tmp_path):
    children = {p.pid for p in multiprocessing.active_children()}
    marker = tmp_path/'started'
    start=time.monotonic()
    with pytest.raises((TimeoutError, RuntimeError)):
        run(worker, (mode, str(marker)), timeout=2)
    assert time.monotonic()-start < 4
    assert marker.exists(), 'worker did not start; increase test startup budget'
    assert {p.pid for p in multiprocessing.active_children()} <= children
    assert run(worker, ('ok', None), timeout=3)['ok']  # late result cannot contaminate next request


def test_stop_during_wait_reaps_worker(tmp_path):
    marker=tmp_path/'started'
    def guard():
        if marker.exists(): raise InterruptedError('stop')
    with pytest.raises(InterruptedError):
        run(worker, ('hang', str(marker)), timeout=3, guard=guard)
    assert not multiprocessing.active_children()


def test_no_large_pipe_receive_can_hang():
    assert len(run(worker, ('large', None), timeout=3)) == 2_000_000


def test_result_after_deadline_rejected(monkeypatch, tmp_path):
    import win10_bridge_mcp.bounded_worker as module
    actual=module.time.monotonic
    marker=tmp_path/'started'
    monkeypatch.setattr(module.time, 'monotonic', lambda: actual() + (10 if marker.exists() else 0))
    with pytest.raises(TimeoutError): run(worker, ('ok', str(marker)), timeout=3)


def test_deadline_and_stop_rechecked_after_decode(monkeypatch):
    import win10_bridge_mcp.bounded_worker as module
    original=module._decode
    state={'stopped': False}
    def decode(value):
        result=original(value)
        state['stopped']=True
        return result
    def guard():
        if state['stopped']: raise InterruptedError('stop during decoding')
    monkeypatch.setattr(module, '_decode', decode)
    with pytest.raises(InterruptedError): run(worker, ('ok', None), timeout=3, guard=guard)


def test_unreaped_worker_triggers_parent_stop(monkeypatch):
    import win10_bridge_mcp.bounded_worker as module
    from types import SimpleNamespace
    stopped=[]
    class Unkillable:
        pid=999
        def start(self): pass
        def is_alive(self): return True
        def join(self, timeout): pass
        def terminate(self): pass
        def kill(self): pass
    context=SimpleNamespace(Event=multiprocessing.get_context('spawn').Event,
                            Process=lambda **_: Unkillable())
    monkeypatch.setattr(module.multiprocessing, 'get_context', lambda _: context)
    with pytest.raises(RuntimeError, match='Unable to kill'):
        run(worker, ('ok', None), timeout=0, on_unreaped=lambda: stopped.append(True))
    assert stopped==[True]
