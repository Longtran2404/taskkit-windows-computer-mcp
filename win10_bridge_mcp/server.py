"""Local stdio MCP server: capture in background, GUI mouse only with consent.

No binary modifications, no injection, no PostMessage background spoofing.
An MCP screenshot is sent to the configured AI client; treat it as shared data.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import threading
import sys
import time
import uuid
from datetime import datetime, timezone
from functools import wraps

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent

from .policy import CaptureRegistry, validate_mouse, UnsupportedControlError
from .config import load_config
from .consent import ConsentGate
from .capture_policy import CAPTURE_MODES, choose_region, rect_data, validate_pixels

APP_NAME = "TaskKit.vn Windows Computer Bridge MCP"
mcp = FastMCP(APP_NAME)
REGISTRY = CaptureRegistry()
MOUSE_MUTEX = threading.RLock()
CONSENT = ConsentGate()
APP_CONSENT = ConsentGate("semantic_control_mode")
CAPTURE_CONSENT = ConsentGate("capture_consent_mode")


ERROR_CODES = {InterruptedError: "stop_or_intervention", PermissionError: "permission_denied",
               TimeoutError: "native_timeout", FileExistsError: "file_exists",
               ValueError: "invalid_request", OSError: "native_or_file_error",
               UnsupportedControlError: "unsupported_control"}


def tool():
    """Register a structured MCP boundary; direct Python calls keep exceptions."""
    def decorate(function):
        @wraps(function)
        def boundary(*args, **kwargs):
            try:
                result = function(*args, **kwargs)
                if isinstance(result, dict):
                    return CallToolResult(structuredContent=result, content=[
                        TextContent(type="text", text=json.dumps(result, ensure_ascii=False))])
                return result
            except Exception as exc:
                code = next((v for k, v in ERROR_CODES.items() if isinstance(exc, k)), "operation_failed")
                error = {"ok": False, "error": {"code": code, "message": str(exc),
                         "effects_verified": False}}
                return CallToolResult(isError=True, structuredContent=error,
                                      content=[TextContent(type="text", text=json.dumps(error, ensure_ascii=False))])
        mcp.tool(structured_output=False)(boundary)
        return function
    return decorate


def running(native=None):
    from .viewer import stopped
    if stopped():
        raise InterruptedError("Preview stop is permanent; restart bridge locally")
    native = backend() if native is None else native
    native.enable_session_stop()
    native._stop_if_needed()
    return native


def verify_ticket(native, win, token):
    running(native)
    current = native.get_window(win.id, frozenset({win.exe}))
    if current.id != win.id or current.rect != win.rect or current.dpi != win.dpi:
        raise ValueError("Window identity/geometry/DPI changed; capture again")
    REGISTRY.verify(token, current.id, current.rect, dpi=current.dpi)
    running(native)
    return current


def authorize(cfg, native, summary):
    running(native)
    if cfg["mouse_control_mode"] == "disabled":
        raise PermissionError("Physical input disabled in local config")
    if cfg["mouse_control_mode"] == "foreground_session":
        require_session(cfg)
    elif not ask_local_consent(summary):
        raise PermissionError("Owner declined local consent")
    running(native)


def action_guard(cfg, native):
    running(native)
    current_cfg = load_config()
    if current_cfg["allowed"] != cfg["allowed"] or current_cfg["mouse_control_mode"] != cfg["mouse_control_mode"]:
        raise PermissionError("Configuration changed during operation; input aborted")
    if cfg["mouse_control_mode"] == "foreground_session":
        CONSENT.check(cfg)




def backend():
    # Delay Win32 import for pure-Python policy unit tests on other operating systems.
    from . import windows_native
    return windows_native


@tool()
def bridge_status() -> dict:
    """Read capabilities without arming input, moving the cursor or clearing stop."""
    cfg = load_config()
    from .viewer import stopped
    available = sys.platform == "win32"
    native = backend() if available else None
    if native:
        native.enable_session_stop()
    is_stopped = stopped() or bool(native and native.SESSION_STOP.is_set())
    app_scope = dict(cfg, consent_window_id=APP_CONSENT.scope[2]) if APP_CONSENT.scope else cfg
    app_armed = APP_CONSENT.armed(app_scope) and not is_stopped
    capture_scope = dict(cfg, consent_scope_key=CAPTURE_CONSENT.scope[3]) if CAPTURE_CONSENT.scope else cfg
    stored_capture_scope = json.loads(CAPTURE_CONSENT.scope[3]) if CAPTURE_CONSENT.scope else None
    capture_armed = (CAPTURE_CONSENT.armed(capture_scope) and not is_stopped and
                     bool(stored_capture_scope and stored_capture_scope[2] == cfg["capture_modes"]))
    return {
        "developed_by": "TaskKit.vn - Minh Long Tran", "homepage": "https://taskkit.vn",
        "platform": sys.platform, "windows_available": available,
        "capture": {"backend": "explicit_by_mode", "deadline_seconds": 3,
                    "backends_by_mode": {"window": "PrintWindow", "monitor": "GDI BitBlt",
                                         "virtual_desktop": "GDI BitBlt", "region": "GDI BitBlt"},
                    "status": "best_effort_unverified" if available else "unavailable",
                    "gpu_viewport_verified": False, "desktop_fallback": False,
                    "mapping": "window: outer-window pixels; desktop modes: absolute physical bounds; per-monitor awareness required",
                    "windows_graphics_capture": "not_implemented",
                    "enabled_modes": cfg["capture_modes"], "available_modes": sorted(CAPTURE_MODES),
                    "consent_mode": cfg["capture_consent_mode"],
                    "consent_session_armed": capture_armed,
                    "consent_remaining_seconds": round(max(0, CAPTURE_CONSENT.expires - time.monotonic()), 1) if capture_armed else 0,
                    "consent_scope": stored_capture_scope[:2] if capture_armed else None,
                    "desktop_modes_issue_input_tokens": False},
        "uia_deadline_seconds": 3,
        "mouse_mode": cfg["mouse_control_mode"],
        "session_armed": CONSENT.armed(cfg) and not is_stopped,
        "session_max_seconds": 300,
        "session_stopped": is_stopped,
        "allowed_processes": sorted(cfg["allowed"]),
        "full_mouse": ["move", "click", "double_click", "drag", "hold", "vertical wheel", "horizontal wheel", "left", "right", "middle", "x1", "x2", "ctrl", "shift", "alt", "space"],
        "concurrent_desktop_mouse": False,
        "app_only": {"mode": cfg["semantic_control_mode"],
                     "actions": ["set_value", "invoke", "select", "scroll"],
                     "requires_control_pattern": True, "physical_input_fallback": False,
                     "bridge_changes_focus": False, "live_windows_verified": False,
                     "session_armed": app_armed,
                     "consent_remaining_seconds": round(max(0, APP_CONSENT.expires - time.monotonic()), 1) if app_armed else 0,
                     "session_window_id": APP_CONSENT.scope[2] if app_armed else None,
                     "note": "Application/provider may change its own UI/focus; unsupported controls are refused."},
        "emergency_stop": "Esc/F12/preview close latches stop until local process restart",
        "local_preview": "optional; opening never clears stop or grants input consent",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Physical SendInput shares mouse/focus. Concurrent work needs an app API or separate Windows desktop."
    }


@tool()
def inspect_windows() -> dict:
    """List only explicitly allowlisted, non-minimized desktop windows."""
    cfg = load_config()
    running()
    wins = backend().enumerate_windows(cfg["allowed"])
    return {"windows": [
        {"window_id": w.id, "title": w.title, "exe": w.exe,
         "pid": w.pid, "dpi": w.dpi, "rect": {"x": w.rect.left, "y": w.rect.top,
                              "width": w.rect.width, "height": w.rect.height}}
        for w in wins]}


def require_session(cfg):
    if cfg["mouse_control_mode"] != "foreground_session":
        raise PermissionError("Owner must enable foreground_session locally for semantic actions")
    native = running()
    CONSENT.require(cfg, ask_local_consent, lambda: running(native))
    action_guard(cfg, native)
    return native


@tool()
def inspect_controls(window_id: str) -> dict:
    """Read bounded UI Automation controls of an allowed window; omit passwords."""
    from . import ui_access
    cfg = load_config()
    native = running()
    with MOUSE_MUTEX:
        win = native.get_window(window_id, cfg["allowed"])
        controls = ui_access.inspect(win, lambda: native.check_window(win))
        native.check_window(win)
        return {"window_id": window_id, "controls": controls}


@tool()
def control_action(window_id: str, capture_id: str, automation_id: str,
                   action: str, value: str = "", dry_run: bool = True) -> dict:
    """Set an edit value or invoke an identified button using foreground UI Automation.

    First inspect_controls and capture. action is set_value or invoke. Passwords
    are excluded. Invocation alone does not certify that a save/open succeeded.
    """
    from . import ui_access
    if action not in {"set_value", "invoke"} or len(value) > 4000 or "\x00" in value:
        raise ValueError("Unsupported action or value too long")
    value.encode("utf-16-le")
    cfg = load_config()
    native = running()
    with MOUSE_MUTEX:
        win = native.get_window(window_id, cfg["allowed"])
        verify_ticket(native, win, capture_id)
        if dry_run:
            return {"dry_run": True, "action": action, "automation_id": automation_id}
        require_session(cfg)
        verify_ticket(native, win, capture_id)
        native._activate(win)
        verify_ticket(native, win, capture_id)
        action_guard(cfg, native)
        REGISTRY.consume(capture_id)
        if action == "set_value":
            actual = ui_access.value(win, automation_id, value,
                                      guard=lambda: (action_guard(cfg, native), native.check_window(win, foreground=True)),
                                      deadline=CONSENT.expires)
            return {"value_matches": actual == value, "notice": "Capture to verify UI"}
        ui_access.invoke(win, automation_id,
                         lambda: (action_guard(cfg, native), native.check_window(win, foreground=True)),
                         deadline=CONSENT.expires)
        return {"invoke_requested": True, "notice": "Verify the resulting UI/file; invocation is not completion"}


def app_action_guard(cfg, native, scope, deadline):
    running(native)
    current = load_config()
    if current["allowed"] != cfg["allowed"] or current["semantic_control_mode"] != cfg["semantic_control_mode"]:
        raise PermissionError("App-only configuration changed; operation aborted")
    if time.monotonic() >= deadline:
        raise PermissionError("Local app-only consent expired")
    if cfg["semantic_control_mode"] == "app_session":
        APP_CONSENT.check(scope)


@tool()
def app_control_action(window_id: str, capture_id: str, automation_id: str, action: str,
                       value: str = "", horizontal: str = "none", vertical: str = "none",
                       dry_run: bool = True) -> dict:
    """App-scoped semantic UIA without bridge mouse/keyboard/focus changes.

    Requires a supported Value/Invoke/SelectionItem/Scroll pattern in the selected
    non-password control. No SendInput, SetFocus or PostMessage fallback. The app
    itself may change UI/focus. Local semantic_control_mode consent is separate
    from physical input. Fresh capture required; default dry run. Scroll amounts:
    none, small_decrement, small_increment, large_decrement, large_increment.
    """
    from . import ui_access
    if (action not in ui_access.APP_PATTERNS or not automation_id or len(automation_id) > 300 or
            len(value) > 4000 or "\x00" in value or "\x00" in automation_id):
        raise ValueError("Supported action, unique nonempty automation ID and bounded value required")
    value.encode("utf-16-le")
    if action == "scroll" and (horizontal not in ui_access.SCROLL_AMOUNTS or vertical not in ui_access.SCROLL_AMOUNTS or
                                horizontal == vertical == "none"):
        raise ValueError("Specify at least one supported scroll amount")
    cfg = load_config()
    native = running()
    with MOUSE_MUTEX:
        win = native.get_window(window_id, cfg["allowed"])
        verify_ticket(native, win, capture_id)
        if dry_run:
            return {"dry_run": True, "execution_mode": "app_only", "action": action,
                    "automation_id": automation_id, "pattern_verified": False,
                    "note": "Capability is resolved at execution; inspect_controls lists advertised patterns."}
        if cfg["semantic_control_mode"] == "disabled":
            raise PermissionError("App-only actions disabled; owner must enable semantic_control_mode locally")
        scope = dict(cfg, consent_window_id=win.id)
        summary = (f"App-only {action} | {win.exe} | {win.title[:80]}\n"
                   f"Window {win.id}, control {automation_id}\n"
                   "Bridge will not move the cursor, send physical input or request focus.\n"
                   "The application/provider may change its own UI or focus. Esc/F12 stops the process.")
        if action == "set_value":
            summary += f"\nSetValue {len(value)} characters: " + json.dumps(value[:160], ensure_ascii=False)
        elif action == "scroll":
            summary += f"\nScroll horizontal={horizontal}, vertical={vertical}"
        if cfg["semantic_control_mode"] == "app_session":
            APP_CONSENT.require(scope, ask_local_consent, lambda: running(native),
                                description=summary + "\nAuthorize SetValue, Invoke, Select and Scroll in this window for up to 5 minutes?")
            deadline = APP_CONSENT.expires
        else:
            if not ask_local_consent(summary + "\nAuthorize exactly this one operation?"):
                raise PermissionError("Owner declined app-only consent")
            deadline = time.monotonic() + 10  # One finite worker, never a reusable grant.
        verify_ticket(native, win, capture_id)
        app_action_guard(cfg, native, scope, deadline)
        REGISTRY.consume(capture_id)
        guard = lambda: (app_action_guard(cfg, native, scope, deadline), native.check_window(win))
        result = ui_access.app_action(win, automation_id, action, value, horizontal, vertical,
                                      guard=guard, deadline=deadline,
                                      authorization={"mode_key": "semantic_control_mode",
                                                     "mode": cfg["semantic_control_mode"],
                                                     "allowed": sorted(cfg["allowed"])})
        guard()
        return {"execution_mode": "app_only", "action": action, **result,
                "bridge_physical_input_sent": False, "bridge_focus_requested": False,
                "notice": "Verify resulting app/UI state. Unsupported patterns never fall back to physical input."}


def _file_matches(path, text):
    # Preserve exact UTF-8 content/newlines. Accept one optional file signature,
    # including when the editor itself starts with a literal U+FEFF.
    expected = text.encode("utf-8")
    with path.open("rb") as source:
        actual = source.read(len(expected) + 4)
    return actual in (expected, b"\xef\xbb\xbf" + expected)


@tool()
def save_notepad_text(window_id: str, capture_id: str, path: str, open_saved: bool = True, dry_run: bool = True) -> dict:
    """Save current classic Notepad editor text via file API, independently of Save As.

    Only absolute local .txt destinations; never overwrite differing existing data.
    Verify written text and optionally open the saved file in a new Notepad window.
    The original editor remains open. Owner-armed foreground_session required.
    """
    import subprocess
    from . import ui_access
    cfg = load_config()
    native = running()
    target = Path(path)
    if not target.is_absolute() or str(target).startswith("\\\\") or target.suffix.lower() != ".txt":
        raise ValueError("Existing local parent directory and absolute .txt path required")
    target = native.local_path(target)
    if not target.parent.is_dir():
        raise ValueError("Existing local parent directory required")
    with MOUSE_MUTEX:
        win = native.get_window(window_id, cfg["allowed"])
        if win.exe != "notepad.exe":
            raise ValueError("This semantic save only supports classic Notepad")
        verify_ticket(native, win, capture_id)
        text = ui_access.value(win, "15", guard=lambda: native.check_window(win))
        verify_ticket(native, win, capture_id)
        if len(text) > 1_000_000:
            raise ValueError("Notepad buffer too large")
        if dry_run:
            return {"dry_run": True, "path": str(target), "characters": len(text)}
        require_session(cfg)
        verify_ticket(native, win, capture_id)
        # Refresh the editor after the human dialog; do not save a pre-consent buffer.
        text = ui_access.value(win, "15", guard=lambda: (action_guard(cfg, native), native.check_window(win)))
        if len(text) > 1_000_000:
            raise ValueError("Notepad buffer too large")
        verify_ticket(native, win, capture_id)
        action_guard(cfg, native)
        REGISTRY.consume(capture_id)
        target = native.local_path(target)
        if target.exists():
            if not _file_matches(target, text):
                raise FileExistsError("Existing file differs; preserved without overwriting")
        else:
            with target.open("x", encoding="utf-8", newline="") as output:
                output.write(text)
        matches = _file_matches(target, text)
        if not matches:
            raise RuntimeError("Saved file verification failed")
        action_guard(cfg, native)
        native.check_window(win)
        if open_saved:
            notepad = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/notepad.exe"
            subprocess.Popen([str(notepad), str(target)])
        return {"saved_verified": True, "path": str(target), "characters": len(text),
                "open_requested": open_saved, "method": "Notepad UIA buffer + UTF-8 file API; original remains open"}


@tool()
def show_live_view(window_id: str) -> dict:
    """Show a local live preview of one allowed window. Esc closes and stops input.

    Opens a separate Windows window; does not enable physical input or upload frames.
    Opening never clears a stop latch or grants physical input consent.
    """
    from .viewer import show_viewer
    cfg = load_config()
    running()
    backend().get_window(window_id, cfg["allowed"])
    with MOUSE_MUTEX:
        return show_viewer(window_id, cfg["allowed"])


@tool()
def close_live_view() -> dict:
    """Close the local preview and latch an emergency stop for physical input."""
    from .viewer import close_viewer
    close_viewer()
    return {"close_requested": True, "input_stopped": True}


@tool()
def capture_window(window_id: str) -> CallToolResult:
    """Best-effort window PNG to MCP client. Nonuniform does not prove GPU pixels.

    Deadline 3 seconds. No desktop fallback. Tokens use physical outer-window
    pixels and expire after 90 seconds; visually verify before requesting input.
    """
    cfg = load_config()
    native = running()
    with MOUSE_MUTEX:
        win = native.get_window(window_id, cfg["allowed"])
        validate_pixels(win.rect)
        scope, deadline = authorize_capture(cfg, native, "window", win.id,
            f"Allowlisted window {win.exe} | {win.title[:80]} | {win.id}")
        guard = lambda: (capture_read_guard(cfg, native, scope, deadline), native.check_window(win))
        guard()
        started = time.monotonic()
        png, method, blank = native.capture_window(win, guard=guard, deadline=deadline,
            authorization={"mode_key": "capture_consent_mode", "mode": cfg["capture_consent_mode"],
                           "allowed": sorted(cfg["allowed"]), "capture_modes": cfg["capture_modes"]})
        native.check_window(win)
        running(native)
        guard()
        if blank:
            raise RuntimeError("Uniform/possibly blank image; no click token issued")
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(png)) as im:
            if im.format != "PNG" or im.size != (win.rect.width, win.rect.height):
                raise RuntimeError("Capture pixel dimensions do not match physical window mapping")
        native.check_window(win)
        running(native)
        t = REGISTRY.issue(win.id, win.rect, method, dpi=win.dpi)
        info = {"window_id": win.id, "capture_id": t.token,
                "mode": "window", "input_authorization": "window_token_only; separate input consent required",
                "width": win.rect.width, "height": win.rect.height, "dpi": win.dpi,
                "origin": [win.rect.left, win.rect.top], "mapping": "outer-window physical pixels",
                "method": method, "status": "best_effort_unverified", "nonuniform": True,
                "gpu_viewport_verified": False, "screenshot_verified_by_user": False,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "expires_in_seconds": REGISTRY.ttl,
                "note": "Borders may be included. Verify target visually. Image is shared with the MCP client."}
        result = CallToolResult(structuredContent=info, content=[
            TextContent(type="text", text=json.dumps(info, ensure_ascii=False)),
            ImageContent(type="image", mimeType="image/png", data=base64.b64encode(png).decode("ascii"))])
        try:
            native.check_window(win)
            running(native)
            guard()
        except Exception:
            REGISTRY.consume(t.token)
            raise
        return result


def authorize_capture(cfg, native, mode, target_key, description):
    running(native)
    if mode not in cfg["capture_modes"]:
        raise PermissionError("Capture mode disabled in local capture_modes; no wider-scope fallback")
    scope = dict(cfg, consent_scope_key=json.dumps([mode, target_key, cfg["capture_modes"]], sort_keys=True))
    summary = (f"Capture and SEND an image to the connected MCP/AI client.\nMode: {mode}\n{description}\n"
               "This is data sharing, not input permission. No physical input or desktop fallback.\n"
               "Images may contain private documents/visible secrets; no automatic redaction.\n")
    if mode != "window":
        summary += "WARNING: this scope includes other applications and sensitive visible contents. No automatic redaction.\n"
    if cfg["capture_consent_mode"] == "session":
        CAPTURE_CONSENT.require(scope, ask_local_consent, lambda: running(native),
                                description=summary + "Authorize repeated capture of this scope for up to 5 minutes?")
        deadline = CAPTURE_CONSENT.expires
    else:
        if not ask_local_consent(summary + "Authorize this one capture?"):
            raise PermissionError("Owner declined capture/data-sharing consent")
        deadline = time.monotonic() + 10
    capture_read_guard(cfg, native, scope, deadline)
    return scope, deadline


def capture_read_guard(cfg, native, scope, deadline):
    running(native)
    current = load_config()
    if (current["capture_modes"] != cfg["capture_modes"] or current["capture_consent_mode"] != cfg["capture_consent_mode"] or
            current["allowed"] != cfg["allowed"] or time.monotonic() >= deadline):
        raise PermissionError("Capture scope/consent expired or configuration changed")
    if cfg["capture_consent_mode"] == "session":
        CAPTURE_CONSENT.check(scope)


@tool()
def inspect_capture_targets() -> dict:
    """Read allowed windows/monitor geometry and enabled modes, without images or consent arming."""
    cfg = load_config()
    native = running()
    layout = native.screen_layout()
    windows = native.enumerate_windows(cfg["allowed"])
    running(native)
    return {**layout.describe(), "enabled_modes": cfg["capture_modes"], "max_pixels": 12_000_000,
            "windows": [{"window_id": w.id, "exe": w.exe, "title": w.title,
                         "dpi": w.dpi, "rect": rect_data(w.rect)} for w in windows],
            "note": "No pixels transferred. Mode must be enabled locally and owner consent is required for images."}


@tool()
def capture_screen(mode: str = "window", window_id: str = "", monitor_id: str = "",
                   left: int = 0, top: int = 0, width: int = 0, height: int = 0,
                   dry_run: bool = True) -> CallToolResult | dict:
    """Explicit window/monitor/virtual_desktop/region image to the MCP client.

    Default dry run. Local enabled-mode + scoped data-sharing consent required.
    Region coordinates are absolute physical pixels. Desktop modes can expose
    other apps; they NEVER issue an input token. No automatic mode/backend fallback.
    """
    if mode not in CAPTURE_MODES:
        raise ValueError("Mode must be window, monitor, virtual_desktop or region")
    cfg = load_config()
    native = running()
    with MOUSE_MUTEX:
        if mode not in cfg["capture_modes"]:
            raise PermissionError("Capture mode is disabled locally")
        if mode == "window":
            if not window_id or monitor_id or any((left, top, width, height)):
                raise ValueError("Window mode takes only window_id")
            win = native.get_window(window_id, cfg["allowed"])
            validate_pixels(win.rect)
            if dry_run:
                return {"dry_run": True, "mode": mode, "window_id": win.id, "rect": rect_data(win.rect),
                        "image_transferred": False, "input_permission_granted": False}
            return capture_window(window_id)
        if window_id:
            raise ValueError("Desktop modes do not target a window or grant input permission")
        layout = native.screen_layout()
        rect = choose_region(mode, layout, monitor_id=monitor_id, left=left, top=top, width=width, height=height)
        if dry_run:
            return {"dry_run": True, "mode": mode, "rect": rect_data(rect), "image_transferred": False,
                    "input_permission_granted": False, "may_include_other_apps": True}
        scope, deadline = authorize_capture(cfg, native, mode,
            [monitor_id, rect_data(rect), layout.describe()],
            f"Monitor ID: {monitor_id or '(virtual desktop/absolute region)'}\nPhysical bounds: " + json.dumps(rect_data(rect)))
        def guard():
            capture_read_guard(cfg, native, scope, deadline)
            if native.screen_layout() != layout:
                raise RuntimeError("Monitor geometry/scale changed; capture discarded")
        guard()
        started = time.monotonic()
        png, method, uniform = native.capture_screen(rect, layout, guard=guard, deadline=deadline,
            authorization={"capture_modes": cfg["capture_modes"], "capture_consent_mode": cfg["capture_consent_mode"],
                           "allowed": sorted(cfg["allowed"])})
        guard()
        from io import BytesIO
        from PIL import Image
        with Image.open(BytesIO(png)) as image:
            if image.format != "PNG" or image.size != (rect.width, rect.height):
                raise RuntimeError("Desktop capture dimensions do not match requested physical region")
        info = {"mode": mode, "monitor_id": monitor_id or None, "observation_id": uuid.uuid4().hex,
                "rect": rect_data(rect), "origin": [rect.left, rect.top], "width": rect.width, "height": rect.height,
                "mapping": "image coordinates + origin = absolute physical desktop pixels",
                "input_authorization": False, "capture_id": None, "method": method,
                "status": "best_effort_unverified", "possibly_uniform": uniform,
                "gpu_viewport_verified": False, "may_include_other_apps": True,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(time.monotonic() - started, 3), "display_layout": layout.describe()}
        result = CallToolResult(structuredContent=info, content=[TextContent(type="text", text=json.dumps(info)),
            ImageContent(type="image", mimeType="image/png", data=base64.b64encode(png).decode("ascii"))])
        guard()
        return result


def _consent_job(summary, cancel):
    import ctypes as ct
    from ctypes import wintypes as wt
    user32 = ct.WinDLL("user32", use_last_error=True)
    user32.MessageBoxW.argtypes = (wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT)
    user32.MessageBoxW.restype = ct.c_int
    return user32.MessageBoxW(None,
        "MCP requests an operation. Review the scope below. Only the local owner should approve.\n\n" + summary,
        "TaskKit.vn - local owner consent", 0x00000004 | 0x00000030 | 0x00040000) == 6


def ask_local_consent(summary: str) -> bool:
    from .bounded_worker import run
    native = running()
    return run(_consent_job, summary, timeout=60, guard=lambda: running(native),
               on_unreaped=native.latch_stop)


@tool()
def mouse_action(
    window_id: str,
    capture_id: str,
    action: str,
    x: int,
    y: int,
    button: str = "left",
    end_x: int = -1,
    end_y: int = -1,
    duration_ms: int = 400,
    steps: int = 16,
    wheel_ticks: int = 1,
    wheel_axis: str = "vertical",
    modifiers: str = "",
    dry_run: bool = True,
) -> dict:
    """Physical mouse control with fresh screenshot + native human consent.

    action: move|click|double_click|drag|hold|scroll. button: left|right|middle|x1|x2.
    Drag holds the button through intermediate positions; hold has a bounded duration.
    wheel_axis: vertical|horizontal. modifiers: ctrl+shift+alt+space subset.
    DEFAULT dry_run=True; input always requires local owner consent.
    Disabled until owner enables a foreground mode in local configuration.
    IMPORTANT: The host's real mouse and focus ARE shared while executing.
    """
    cfg = load_config()
    m = running()
    mods = validate_mouse(action, button, duration_ms, steps, wheel_ticks, wheel_axis, modifiers)
    with MOUSE_MUTEX:
        win = m.get_window(window_id, cfg["allowed"])
        ex = x if end_x == -1 else end_x
        ey = y if end_y == -1 else end_y
        sx, sy = win.rect.absolute(x, y)
        tx, ty = win.rect.absolute(ex, ey)
        if action == "drag" and (ex, ey) == (x, y):
            raise ValueError("Drag must specify a different end point")
        verify_ticket(m, win, capture_id)
        summary = f"{win.exe} | {win.title[:80]}\n{action} {button} from {x},{y} to {ex},{ey} | {duration_ms} ms | wheel={wheel_ticks} {wheel_axis} | mods={mods}"
        if dry_run:
            return {"dry_run": True, "summary": summary,
                    "physical_coordinates": [[sx, sy], [tx, ty]],
                    "mouse_control_mode": cfg["mouse_control_mode"],
                    "note": "No input sent. Set dry_run=false after local owner enables mouse mode."}
        authorize(cfg, m, summary)
        refreshed = verify_ticket(m, win, capture_id)
        REGISTRY.consume(capture_id)
        m.apply_mouse(refreshed, action, button, x, y, ex, ey,
                      duration_ms, steps, wheel_ticks, wheel_axis, mods,
                      guard=lambda: action_guard(cfg, m))
        return {"performed": True, "mouse_action": action,
                "notice": "Sent physical input; software result unverified. Capture again to verify."}


@tool()
def type_text(window_id: str, capture_id: str, text: str, dry_run: bool = True, replace_all: bool = False) -> dict:
    """Type bounded Unicode text in an allowed foreground window after local consent.

    Click the intended editor first and capture again. Text is literal, no shortcuts.
    Esc/F12 stops. Default dry run. Same physical-input config and consent as mouse.
    replace_all=True explicitly selects all text in the focused editor and replaces it.
    """
    if not isinstance(text, str) or not 1 <= len(text) <= 2000:
        raise ValueError("Text must contain 1 to 2000 characters")
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise ValueError("Control characters are not supported; type literal single-line text")
    text.encode("utf-16-le")
    cfg = load_config()
    native = running()
    with MOUSE_MUTEX:
        win = native.get_window(window_id, cfg["allowed"])
        verify_ticket(native, win, capture_id)
        summary = f"{win.exe} | {win.title[:80]}\nType {len(text)} characters (replace all={replace_all}): {text[:160]}"
        if dry_run:
            return {"dry_run": True, "summary": summary}
        authorize(cfg, native, summary)
        current = verify_ticket(native, win, capture_id)
        REGISTRY.consume(capture_id)
        native.apply_text(current, text, replace_all=replace_all, guard=lambda: action_guard(cfg, native))
        return {"performed": True, "characters": len(text), "notice": "Capture again to verify editor contents"}


@tool()
def press_key(window_id: str, capture_id: str, key: str, dry_run: bool = True) -> dict:
    """Press one bounded key or chord, e.g. ctrl+s, ctrl+l, enter, tab, alt+n.

    Only listed keys are accepted; Windows/system keys and Esc are excluded.
    Physical Esc is reserved for stopping the authorized session.
    Capture and verify the resulting UI before the next action.
    """
    cfg = load_config()
    native = running()
    parts = tuple(key.lower().split("+"))
    if not 1 <= len(parts) <= 4 or len(set(parts)) != len(parts) or any(k not in native.KEY_CODES for k in parts):
        raise ValueError("Unsupported key chord")
    if len(parts) > 1 and (any(k not in {"ctrl", "shift", "alt"} for k in parts[:-1]) or parts[-1] in {"ctrl", "shift", "alt"}):
        raise ValueError("Use modifier(s)+one key")
    with MOUSE_MUTEX:
        win = native.get_window(window_id, cfg["allowed"])
        verify_ticket(native, win, capture_id)
        if dry_run:
            return {"dry_run": True, "key": key, "window_id": window_id}
        authorize(cfg, native, f"{win.exe} | {win.title[:80]} Press {key}")
        current = verify_ticket(native, win, capture_id)
        REGISTRY.consume(capture_id)
        native.apply_keys(current, parts, guard=lambda: action_guard(cfg, native))
        return {"performed": True, "key": key, "notice": "Capture again to verify"}


@tool()
def list_drives() -> dict:
    """Read existing local drive roots, for choosing an Explorer destination."""
    import string
    running()
    return {"drives": [f"{letter}:\\" for letter in string.ascii_uppercase if Path(f"{letter}:\\").is_dir()]}


@tool()
def open_directory(path: str) -> dict:
    """Open an existing absolute local directory in Windows Explorer.

    Requires explorer.exe explicitly allowed and foreground_session mode.
    No files/executables/URLs/UNC destinations; Esc stops this action too.
    """
    cfg = load_config()
    if cfg["mouse_control_mode"] != "foreground_session" or "explorer.exe" not in cfg["allowed"]:
        raise PermissionError("Owner must enable foreground_session and allow explorer.exe")
    target = Path(path)
    if not target.is_absolute() or str(target).startswith("\\\\"):
        raise ValueError("Existing absolute local directory required")
    native = running()
    target = native.local_path(target, directory=True)
    if not target.is_dir():
        raise ValueError("Existing absolute local directory required")
    require_session(cfg)
    action_guard(cfg, native)
    os.startfile(str(target))
    return {"open_requested": True, "path": str(target), "notice": "Inspect windows and capture Explorer to verify"}


@tool()
def emergency_release() -> dict:
    """Best-effort release of any injected mouse buttons and modifiers; no dialog."""
    from .viewer import close_viewer
    close_viewer()  # Also stops the separate preview's capture workers.
    native = backend()
    native.latch_stop()
    failures = native.release_all()
    return {"best_effort_release_requested": True, "release_failures": failures,
            "session_stopped": True, "note": "Emergency broad release may affect owner-held keys/buttons"}


def main() -> None:
    # Read config at startup so malformed settings fail fast.
    cfg = load_config()
    if sys.platform == "win32":
        running()  # Stop watcher in every mode; configuration does not grant consent.
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
