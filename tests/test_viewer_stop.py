import pytest
from win10_bridge_mcp import viewer, server


def test_close_latches_stop():
    viewer.close_viewer()
    assert viewer.stopped()
    with pytest.raises(InterruptedError): viewer.show_viewer('w', {'notepad.exe'})
    assert viewer.STOP.is_set()
    assert viewer._closed.is_set()


def test_preview_cannot_resume_dead_process(monkeypatch):
    class Dead:
        def is_alive(self): return False
    monkeypatch.setattr(viewer, '_process', Dead())
    with pytest.raises(InterruptedError): viewer.show_viewer('w', {'notepad.exe'})


@pytest.mark.parametrize('mode', ['disabled', 'foreground_confirm_each', 'foreground_session'])
def test_all_modes_stop_capture_uia_input(bridge, ticket, mode):
    native, cfg = bridge
    cfg['mouse_control_mode'] = mode
    native.SESSION_STOP.set()
    win_id = native.current.id
    calls = [lambda: server.capture_window(win_id), lambda: server.inspect_controls(win_id),
             lambda: server.mouse_action(win_id, ticket, 'click', 10, 10),
             lambda: server.type_text(win_id, ticket, 'x'),
             lambda: server.press_key(win_id, ticket, 's'),
             lambda: server.inspect_windows(), lambda: server.show_live_view(win_id),
             lambda: server.control_action(win_id, ticket, '15', 'set_value'),
             lambda: server.app_control_action(win_id, ticket, 'item', 'invoke')]
    for call in calls:
        with pytest.raises(InterruptedError): call()
    assert not native.operations


def test_emergency_stop_closes_shared_preview_and_never_rearms(bridge):
    native, _=bridge
    result=server.emergency_release()
    assert result['session_stopped']
    assert native.SESSION_STOP.is_set()
    assert viewer._closed.is_set()
    with pytest.raises(InterruptedError): server.capture_window(native.current.id)
    with pytest.raises(InterruptedError): viewer.show_viewer(native.current.id, {'notepad.exe'})


def test_preview_start_is_not_mistaken_for_dead_process(bridge, monkeypatch):
    import queue
    import sys
    import threading
    from types import SimpleNamespace
    native, _=bridge
    monkeypatch.setitem(sys.modules, 'win10_bridge_mcp.windows_native', native)
    class Process:
        def __init__(self, *, target, args):
            self.args=args; self.alive=False
        def start(self):
            assert not viewer.stopped(), 'watcher saw a not-yet-started preview as dead'
            self.alive=True
            self.args[3].set()
        def is_alive(self): return self.alive
    context=SimpleNamespace(Event=threading.Event, Queue=queue.Queue, Process=Process)
    monkeypatch.setattr(viewer.multiprocessing, 'get_context', lambda _: context)
    assert viewer.show_viewer(native.current.id, {'notepad.exe'})['visible']
    assert not viewer.stopped()


@pytest.mark.parametrize('stop_check', [2, 3])
def test_stop_at_preview_event_publication_or_ready(bridge, monkeypatch, stop_check):
    import queue
    import sys
    import threading
    from types import SimpleNamespace
    native, _=bridge
    monkeypatch.setitem(sys.modules, 'win10_bridge_mcp.windows_native', native)
    calls=[]
    def check():
        calls.append(1)
        if len(calls)==stop_check:
            native.SESSION_STOP.set()
        if native.SESSION_STOP.is_set(): raise InterruptedError('simultaneous stop')
    native._stop_if_needed=check
    class Process:
        def __init__(self, *, target, args): self.args=args; self.alive=False
        def start(self): self.alive=True; self.args[3].set()
        def is_alive(self): return self.alive
        def terminate(self): self.alive=False
        def join(self, timeout): pass
    context=SimpleNamespace(Event=threading.Event, Queue=queue.Queue, Process=Process)
    monkeypatch.setattr(viewer.multiprocessing, 'get_context', lambda _: context)
    with pytest.raises(InterruptedError): viewer.show_viewer(native.current.id, {'notepad.exe'})
    assert native.SESSION_STOP.is_set()


def test_preview_startup_error_retains_diagnostics(bridge, monkeypatch):
    import queue
    import sys
    import threading
    from types import SimpleNamespace
    native, _=bridge
    monkeypatch.setitem(sys.modules, 'win10_bridge_mcp.windows_native', native)
    class Process:
        def __init__(self, *, target, args): self.args=args; self.alive=False
        def start(self):
            self.alive=True
            self.args[4].put('Tkinter unavailable')
            self.args[2].set(); self.args[3].set()
        def is_alive(self): return self.alive
        def terminate(self): self.alive=False
        def join(self, timeout): pass
    context=SimpleNamespace(Event=threading.Event, Queue=queue.Queue, Process=Process)
    monkeypatch.setattr(viewer.multiprocessing, 'get_context', lambda _: context)
    with pytest.raises(RuntimeError, match='Tkinter unavailable'):
        viewer.show_viewer(native.current.id, {'notepad.exe'})
    assert viewer.stopped()
