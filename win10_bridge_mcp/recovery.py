"""Recover uncertain native outcomes through observation, never input replay.

This gate is separate from the owner's irreversible-for-this-task Esc latch.
No user approval is needed to inspect and capture the already authorized task.
"""
from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_generation = 0
_pending = False
_inspected = False
_minimum_capture_time = 0.0
_failure = None


def status():
    with _lock:
        return {'recovery_required': _pending, 'windows_inspected': _inspected,
                'last_uncertain_operation': dict(_failure) if _failure else None,
                'next_step': ('inspect_windows, then capture_window of the current target/dialog; continue the authorized task without replaying the uncertain action'
                              if _pending else 'No timeout recovery pending'),
                'requires_owner_restart': False}


def pause(operation, reason):
    global _generation, _pending, _inspected, _minimum_capture_time, _failure
    with _lock:
        _generation += 1
        _pending, _inspected = True, False
        _minimum_capture_time = time.monotonic()
        _failure = {'operation': operation, 'reason': reason, 'result_unknown': True}


def observation():
    with _lock:
        return _generation, _inspected


def inspected(observation):
    global _inspected
    with _lock:
        if _pending and observation[0] == _generation:
            _inspected = True


def captured(observation):
    global _pending, _minimum_capture_time
    with _lock:
        # An in-flight capture/inspection from before the failure cannot recover
        # the task. A blank/failed/desktop capture must never call this hook.
        if _pending and observation == (_generation, True):
            _minimum_capture_time = time.monotonic()
            _pending = False


def require_ready():
    with _lock:
        if _pending:
            raise RuntimeError('Native result unknown. Session is still active; inspect_windows and capture_window of the current target/dialog, then continue the authorized task. Do not restart the session or replay the uncertain action automatically.')


def require_capture(ticket):
    require_ready()
    with _lock:
        if _minimum_capture_time and (ticket is None or ticket.created < _minimum_capture_time):
            raise ValueError('Capture predates timeout recovery. Capture the target window again before input.')


def reset():
    """Only an explicitly owner-authorized new task resets recovery history."""
    global _generation, _pending, _inspected, _minimum_capture_time, _failure
    with _lock:
        _generation += 1
        _pending, _inspected = False, False
        _minimum_capture_time = 0.0
        _failure = None
