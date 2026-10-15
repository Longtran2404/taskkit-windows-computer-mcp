"""Isolate blocking Win32/UIA calls. No retries, shell, files or input replay."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

TIMEOUT_SECONDS = 5.0
_slots = threading.BoundedSemaphore(2)
_state_lock = threading.Lock()
_active = {}
_last_failure = None
OPERATIONS = {'capture', 'inspect', 'value', 'invoke', 'focus'}


def status():
    with _state_lock:
        return {'timeout_seconds': TIMEOUT_SECONDS, 'active_operations': list(_active.values()),
                'last_failure': dict(_last_failure) if _last_failure else None}


def _failed(operation, reason, uncertain):
    global _last_failure
    with _state_lock:
        _last_failure = {'operation': operation, 'reason': reason, 'result_unknown': uncertain}


def call(operation, payload, *, mutating=False, timeout=TIMEOUT_SECONDS):
    """A timed-out worker is killed and reaped; the app is never terminated.

    A mutation may already have reached its provider: latch stop and require
    inspection, never retry the action. Read-only failures keep input state.
    """
    if operation not in OPERATIONS:
        raise ValueError('Unsupported native worker operation')
    native = None
    if mutating:
        from . import windows_native as native
        native._stop_if_needed()
    deadline = time.monotonic() + timeout
    if not _slots.acquire(timeout=timeout):
        raise TimeoutError('Native workers busy; no operation was sent. Inspect status before trying again.')
    process = None
    try:
        env = dict(os.environ)
        # Use this exact package in a fresh interpreter, including source tests.
        env['PYTHONPATH'] = str(Path(__file__).resolve().parent.parent)
        env['PYTHONUTF8'] = '1'
        # Windows venv python.exe is a redirector with another Python child.
        # Launch the real interpreter with our import paths so kill/reap owns
        # the actual COM/PrintWindow process, not just its redirector parent.
        paths = [str(Path(__file__).resolve().parent.parent), *sys.path]
        bootstrap = f"import sys,runpy;sys.path[:]={paths!r};runpy.run_module('win10_bridge_mcp.native_worker',run_name='__main__')"
        interpreter = getattr(sys, '_base_executable', None) or sys.executable
        process = subprocess.Popen([interpreter, '-c', bootstrap],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        with _state_lock:
            _active[process.pid] = {'operation': operation, 'worker_pid': process.pid,
                                    'mutating': mutating}
        message = json.dumps({'operation': operation, 'payload': payload}).encode('utf-8')
        while True:
            if native is not None:
                native._stop_if_needed()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if native is not None:
                    native.SESSION_STOP.set()
                    native.release_all()
                _failed(operation, 'timeout', mutating)
                suffix = (' Result unknown; inspect windows/dialogs before a new owner-authorized task. Do not replay this action.'
                          if mutating else ' No input was sent; inspect windows or use capture_desktop to diagnose.')
                raise TimeoutError(f'Native {operation} timed out after {timeout:g}s; worker stopped.' + suffix)
            try:
                stdout, stderr = process.communicate(input=message, timeout=min(.05, remaining))
                break
            except subprocess.TimeoutExpired:
                message = None
        if process.returncode:
            if native is not None:
                native.SESSION_STOP.set()
            _failed(operation, 'worker exited', mutating)
            raise RuntimeError(f'Native {operation} worker exited. Inspect the application before another action.')
        result = json.loads(stdout)
        if not result['ok']:
            error_type = {'ValueError': ValueError, 'PermissionError': PermissionError,
                          'InterruptedError': InterruptedError, 'OSError': OSError}.get(result['type'], RuntimeError)
            raise error_type(result['error'])
        return result['value']
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.communicate()
            with _state_lock:
                _active.pop(process.pid, None)
        _slots.release()


def _dispatch(operation, payload):
    from . import windows_native as native
    hwnd = payload['hwnd']
    if operation == 'capture':
        win = native.get_window(payload['window_id'], frozenset({payload['exe']}))
        if [win.rect.left, win.rect.top, win.rect.right, win.rect.bottom] != payload['rect']:
            raise RuntimeError('Window moved during capture; inspect and capture again')
        png, method, blank = native._capture_window(win)
        current = native.get_window(win.id, frozenset({win.exe}))
        if current.rect != win.rect:
            raise RuntimeError('Window moved during capture; no input ticket issued')
        return {'png': base64.b64encode(png).decode('ascii'), 'method': method, 'blank': blank}
    from . import ui_access
    return getattr(ui_access, '_' + operation)(hwnd, **payload.get('arguments', {}))


def main():
    try:
        request = json.loads(sys.stdin.buffer.read())
        if request['operation'] not in OPERATIONS:
            raise ValueError('Unsupported native worker operation')
        result = {'ok': True, 'value': _dispatch(request['operation'], request['payload'])}
    except Exception as exc:
        result = {'ok': False, 'type': type(exc).__name__, 'error': str(exc)}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
