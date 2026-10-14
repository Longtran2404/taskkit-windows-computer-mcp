"""Disposable spawn workers: a hung native call cannot hold the server forever.

Results stay in an owner-only temporary directory until the worker has exited.
No large pipe recv (which itself could block), persistent worker or late callback.
"""
from __future__ import annotations

import base64
import json
import multiprocessing
from pathlib import Path
import tempfile
import time
from .policy import UnsupportedControlError

MAX_RESULT_BYTES = 70_000_000


def _encode(value):
    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    return value


def _decode(value):
    if isinstance(value, dict):
        if set(value) == {"__bytes__"}:
            return base64.b64decode(value["__bytes__"], validate=True)
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def _entry(target, payload, cancel, destination):
    try:
        result = {"ok": True, "value": _encode(target(payload, cancel))}
    except Exception as exc:
        result = {"ok": False, "kind": type(exc).__name__, "error": str(exc)[:1500]}
    Path(destination).write_text(json.dumps(result, ensure_ascii=True), encoding="utf-8")


def run(target, payload, *, timeout=3.0, guard=lambda: None, on_unreaped=lambda: None):
    """Run an importable target(payload, cancel) with an absolute deadline.

    Mutation timeouts/aborts have indeterminate effects; callers must verify UI
    state before retrying. The parent guard runs during waits and before return.
    """
    guard()
    ctx = multiprocessing.get_context("spawn")
    cancel = ctx.Event()
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryDirectory(prefix="taskkit-worker-") as directory:
        output = Path(directory) / "result.json"
        process = ctx.Process(target=_entry, args=(target, payload, cancel, str(output)))
        try:
            process.start()
            while process.is_alive():
                guard()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Native worker deadline exceeded; result discarded. Effects may be indeterminate; verify before retry.")
                process.join(min(0.01, max(0, deadline - time.monotonic())))
            guard()
            if time.monotonic() >= deadline:
                raise TimeoutError("Native worker returned late; result discarded")
            if process.exitcode != 0 or not output.exists():
                raise RuntimeError(f"Native worker crashed (exit={process.exitcode}); no result accepted")
            if output.stat().st_size > MAX_RESULT_BYTES:
                raise RuntimeError("Native worker result exceeds size limit")
            result = json.loads(output.read_text(encoding="utf-8"))
            guard()
            if time.monotonic() >= deadline:
                raise TimeoutError("Native worker result exceeded deadline; discarded")
            if not result["ok"]:
                error = {"ValueError": ValueError, "PermissionError": PermissionError,
                         "InterruptedError": InterruptedError, "OSError": OSError,
                         "UnsupportedControlError": UnsupportedControlError}.get(result["kind"], RuntimeError)
                raise error(result["error"])
            value = _decode(result["value"])
            guard()
            if time.monotonic() >= deadline:
                raise TimeoutError("Native worker result decoding exceeded deadline; discarded")
            return value
        finally:
            cancel.set()
            if process.pid is not None:
                if process.is_alive():
                    process.terminate()
                    process.join(0.25)
                if process.is_alive():
                    process.kill()
                    process.join(0.25)
                if process.is_alive():
                    on_unreaped()
                    raise RuntimeError("Unable to kill native worker; stop the bridge process locally")
                process.close()
