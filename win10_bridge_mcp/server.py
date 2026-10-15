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
from functools import partial, wraps
from typing import Literal

import anyio

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent

from .policy import CaptureRegistry, normalize_allowlist, validate_mouse, process_allowed
from . import recovery

APP_NAME = "TaskKit.vn Windows Computer Bridge MCP"
SESSION_FINISH_INSTRUCTIONS = (
    'After the final verification of computer work, before ending your response, '
    'waiting for the owner, or switching to work that no longer uses the desktop, '
    'call end_control_session. Close TaskKit overlays and release controls while '
    'leaving application documents open. Do not leave the control session armed '
    'between tasks. For a new owner-authorized computer task, call '
    'start_control_session, inspect windows and capture again. Never replay a '
    'cancelled or uncertain operation. A native timeout is recovered by inspection '
    'and a fresh capture, not by asking the owner to restart.'
)
mcp = FastMCP(APP_NAME, instructions=SESSION_FINISH_INSTRUCTIONS)
REGISTRY = CaptureRegistry()
MOUSE_MUTEX = threading.RLock()
_session_end_reason = None


def verify_capture(capture_id, window_id, rect):
    ticket = REGISTRY.verify(capture_id, window_id, rect)
    recovery.require_ready()
    return ticket


def tool(**options):
    """Keep the MCP transport responsive while native calls wait in a thread.

    Direct Python callers retain the existing synchronous function interface.
    In particular status, window discovery and emergency stop can still run
    while another request is waiting for a blocked application provider.
    """
    def register(function):
        @wraps(function)
        async def dispatch(*args, **kwargs):
            return await anyio.to_thread.run_sync(partial(function, *args, **kwargs))
        if function.__name__ not in {'end_control_session', 'emergency_release', 'close_live_view'}:
            dispatch.__doc__ = (function.__doc__ or '') + (
                '\n\nWhen computer work is finished or you are handing control back '
                'to the owner, call end_control_session before your final response '
                'or waiting for user input. Leave application documents open.'
            )
        mcp.tool(**options)(dispatch)
        return function
    return register


def load_config() -> dict:
    cfgfile = Path(os.environ.get("WIN10_BRIDGE_CONFIG", str(Path.home() / "Win10_ComputerBridge" / "bridge_config.json")))
    cfg = {"allow_processes": ["notepad.exe"], "mouse_control_mode": "disabled"}
    if cfgfile.exists():
        raw = json.loads(cfgfile.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("Configuration must be JSON object")
        if set(raw) - {"allow_processes", "mouse_control_mode", "notes"}:
            raise ValueError("Unexpected configuration keys")
        cfg.update(raw)
    cfg["allowed"] = normalize_allowlist(cfg["allow_processes"])
    if cfg["mouse_control_mode"] not in {"disabled", "foreground_confirm_each", "foreground_session"}:
        raise ValueError("mouse_control_mode must be disabled, foreground_confirm_each or foreground_session")
    return cfg


def backend():
    # Delay Win32 import for pure-Python policy unit tests on other operating systems.
    from . import windows_native
    return windows_native


@tool()
def bridge_status() -> dict:
    """Read-only bridge capabilities, owner cancellation and timeout recovery.

    Timeout alone never cancels the authorized task. If timeout_recovery is
    required, inspect_windows then capture_window and continue without asking
    for owner restart. session_stopped still means Esc/F12/preview cancellation;
    that stop, or a finished end_control_session, requires a new owner-authorized
    task and is never cleared by reads. End control when finished or waiting.
    """
    cfg = load_config()
    from . import __version__
    from . import indicator, viewer, native_worker
    return {
        "version": __version__,
        "backend": "native_win32",
        "initialization": "automatic on MCP startup / first native call",
        "requires_sky": False,
        "capture_diagnostics": "diagnose_capture: bounded PrintWindow test, optional explicit desktop observation, no input ticket",
        "control_indicator_active": indicator.active(),
        "control_indicator_displays": indicator.status(),
        "native_operations": native_worker.status(),
        "timeout_recovery": recovery.status(),
        "session_lifecycle": {"end_tool": "end_control_session", "last_end_reason": _session_end_reason,
                              "finish_policy": "Call end_control_session when done, before final response, waiting for the owner, or leaving desktop work"},
        "control_indicator": "automatic click-through monitor borders + TaskKit MCP in use - ESC to cancel.",
        "developed_by": "TaskKit.vn - Minh Long Tran",
        "homepage": "https://taskkit.vn",
        "windows_capture": "PrintWindow (can fail for GPU CAD viewports)",
        "capture_mode": "background, no cursor movement, window must not be minimized",
        "mouse_mode": cfg["mouse_control_mode"],
        "session_stopped": (backend().SESSION_STOP.is_set() or viewer.stopped()) if cfg["mouse_control_mode"] == "foreground_session" else None,
        "new_session_tool": "start_control_session (only after owner requests a new task; never retry the cancelled task automatically)",
        "allowed_processes": sorted(cfg["allowed"]),
        "application_scope": "all_applications" if "*" in cfg["allowed"] else "selected_applications",
        "desktop_view": "list_monitors / capture_desktop / show_live_view(source='desktop', monitor_id='all', fullscreen=True)",
        "dialog_handling": "inspect_windows reports enabled, owner_window_id and blocked_by_window_id; target and capture the dialog before input",
        "full_mouse": ["move", "click", "double_click", "drag", "hold", "scroll vertical", "scroll horizontal", "left", "right", "middle", "x1", "x2", "ctrl", "shift", "alt", "space"],
        "concurrent_desktop_mouse": False,
        "emergency_stop": "Esc or F12 aborts input; Esc closes preview; buttons released in finally",
        "local_preview": "optional show_live_view / close_live_view; closing stops the authorized session",
        "live_view": viewer.status(),
        "note": "For uninterrupted concurrent GUI work use a separate VM/workstation; Revit API MCP is preferred for BIM edits."
    }


@tool()
def inspect_windows() -> dict:
    """List visible non-minimized windows in the owner's application scope.

    allow_processes=["*"] includes all identifiable applications, including
    newly opened ones. Otherwise only the configured process names are listed.
    After an uncertain native timeout, inspect here then capture_window of the
    current target/dialog to recover the same task without owner restart.
    """
    cfg = load_config()
    native = backend()
    observation = recovery.observation()
    wins = native.enumerate_windows(cfg["allowed"])
    result = {"windows": [
        {"window_id": w.id, "title": w.title, "exe": w.exe,
         "pid": w.pid, "rect": {"x": w.rect.left, "y": w.rect.top,
                              "width": w.rect.width, "height": w.rect.height},
         **native.window_details(w, wins)}
        for w in wins]}
    recovery.inspected(observation)
    return result


@tool()
def list_monitors() -> dict:
    """List actual monitor IDs, primary monitor and virtual-desktop coordinates."""
    from .desktop import list_monitors, monitor_bounds
    monitors = list_monitors()
    bounds = monitor_bounds(monitors)
    return {"monitors": monitors, "virtual_desktop": {"x": bounds.left, "y": bounds.top,
            "width": bounds.width, "height": bounds.height}}


@tool(structured_output=False)
def capture_desktop(monitor_id: str = "all", max_edge: int = 4096) -> CallToolResult:
    """Screenshot one monitor or all monitors together, including visible dialogs.

    Read-only: no focus or pointer change. Requires owner-selected all-app scope.
    Returns origin/scales for negative monitor coordinates. No input ticket;
    inspect and capture the target window/dialog before mouse or keyboard input.
    Desktop pixels are returned to the AI client, not only kept locally.
    """
    from .desktop import capture
    if "*" not in load_config()["allowed"]:
        raise PermissionError('Desktop capture requires owner-authorized allow_processes=["*"]')
    png, info = capture(monitor_id, max_edge)
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(info)),
            ImageContent(type="image", mimeType="image/png", data=base64.b64encode(png).decode('ascii'))])


@tool(structured_output=False)
def diagnose_capture(window_id: str, include_desktop: bool = False,
                     monitor_id: str = "all", max_edge: int = 4096) -> CallToolResult:
    """Diagnose a blank/failed window capture without input, focus or binary patches.

    Returns a bounded PrintWindow result and, only when explicitly requested,
    a visible desktop screenshot. Desktop observation requires all-app scope
    and may include other applications. Neither image issues an input ticket,
    clears timeout recovery, or rearms an ended/Esc-cancelled session.
    A successful diagnostic is not proof that every GPU viewport renders.
    """
    cfg = load_config()
    if include_desktop and "*" not in cfg["allowed"]:
        raise PermissionError('Desktop diagnostics require owner-authorized allow_processes=["*"]')
    if include_desktop and not 640 <= max_edge <= 8192:
        raise ValueError('max_edge must be 640..8192')
    with MOUSE_MUTEX:
        native = backend()
        win = native.get_window(window_id, cfg["allowed"])
        info = {"window_id": win.id, "requires_sky": False,
                "input_ticket_issued": False, "desktop_requested": include_desktop,
                "note": "Read-only diagnostic. Verify image contents; no input or recovery authorization is issued."}
        images = []
        try:
            png, method, blank = native.capture_window(win)
            info["window_capture"] = {"status": "possibly_blank" if blank else "captured",
                                      "method": method}
            if not blank:
                images.append(ImageContent(type="image", mimeType="image/png",
                                          data=base64.b64encode(png).decode("ascii")))
        except (TimeoutError, RuntimeError, OSError) as exc:
            info["window_capture"] = {"status": "failed", "error_type": type(exc).__name__,
                                      "error": str(exc)[:1200]}
        if include_desktop:
            from .desktop import capture
            try:
                png, meta = capture(monitor_id, max_edge)
                info["desktop_capture"] = dict(meta, status="captured")
                images.append(ImageContent(type="image", mimeType="image/png",
                                          data=base64.b64encode(png).decode("ascii")))
            except (ValueError, RuntimeError, OSError) as exc:
                info["desktop_capture"] = {"status": "failed", "error_type": type(exc).__name__,
                                           "error": str(exc)[:1200]}
        info["image_order"] = (["window"] if info["window_capture"]["status"] == "captured" else []) + (
            ["desktop"] if info.get("desktop_capture", {}).get("status") == "captured" else [])
        info["next_step"] = ("Inspect and capture the target/dialog with capture_window before physical input. "
                             "Desktop observation cannot replace an input ticket. GPU/protected surfaces may remain unsupported.")
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(info, ensure_ascii=False)), *images])


@tool()
def start_control_session() -> dict:
    """Start a NEW owner-authorized task after completion, Esc/F12 or preview close.

    Esc cancels the current task: never call this automatically to retry it.
    Use only when the owner explicitly asks to start/try again or gives a new
    computer-control task. No input, focus change or queued-action replay.
    Invalidates all old capture IDs. Inspect and capture again before input.
    The local configuration must already authorize foreground_session.
    A native timeout does NOT need this tool: inspect_windows and capture_window
    recover the current authorized task without asking the owner to restart it.
    """
    global _session_end_reason
    cfg = load_config()
    if cfg["mouse_control_mode"] != "foreground_session":
        raise PermissionError("Owner must already enable foreground_session in local config")
    with MOUSE_MUTEX:
        REGISTRY.invalidate_all()
        backend().start_new_session()
        recovery.reset()
        _session_end_reason = None
    return {"started": True, "session_stopped": False, "old_captures_invalidated": True,
            "next_step": "Inspect windows and capture again before any input",
            "note": "New task only; cancelled actions are never replayed"}


@tool()
def end_control_session(reason: Literal['completed', 'handoff'] = 'completed') -> dict:
    """Finish computer control when done or before waiting for the owner.

    REQUIRED before the final response or leaving desktop work: stop input,
    release held keys/buttons, close all TaskKit borders/banner and preview,
    invalidate capture tickets. Application windows/documents remain open.
    Idempotent; no confirmation. MCP stays connected for read-only inspection.
    A new owner-authorized task can use start_control_session and fresh captures.
    Do not use this as timeout recovery or replay pending operations.
    """
    global _session_end_reason
    from . import indicator, viewer
    if reason not in {'completed', 'handoff'}:
        raise ValueError('reason must be completed or handoff')
    native = backend()
    # Signal before waiting for the mutex: an in-flight hold/drag/UIA mutation
    # must stop and release its input rather than make shutdown wait for it.
    native.SESSION_STOP.set()
    native.release_all()
    with MOUSE_MUTEX:
        native.SESSION_STOP.set()
        native.release_all()
        REGISTRY.invalidate_all()
        viewer.close_viewer()
        preview_closed = viewer.wait_closed()
        indicator_closed = indicator.close()
        _session_end_reason = reason
    if not preview_closed or not indicator_closed:
        raise RuntimeError('Session input stopped and captures invalidated, but a TaskKit overlay thread has not exited. Call end_control_session again to finish cleanup; do not rearm input.')
    return {"ended": True, "reason": reason, "session_stopped": True,
            "preview_closed": True, "indicator_closed": True, "captures_invalidated": True,
            "applications_left_open": True, "mcp_connected": True,
            "next_step": "For a new owner-authorized computer task, start_control_session then inspect and capture again"}


def require_session(cfg):
    if cfg["mouse_control_mode"] != "foreground_session":
        raise PermissionError("Owner must explicitly enable foreground_session for semantic actions")
    native = backend()
    native.enable_session_stop()
    native._stop_if_needed()
    return native


@tool()
def inspect_controls(window_id: str) -> dict:
    """Read bounded UI Automation controls of an allowed window; omit passwords."""
    from . import ui_access
    cfg = load_config()
    win = backend().get_window(window_id, cfg["allowed"])
    return {"window_id": window_id, "controls": ui_access.inspect(win.hwnd)}


@tool()
def control_action(window_id: str, capture_id: str, automation_id: str,
                   action: str, value: str = "", dry_run: bool = True) -> dict:
    """Set an edit value or invoke an identified button using foreground UI Automation.

    First inspect_controls and capture. action is set_value or invoke. Passwords
    are excluded. Invocation alone does not certify that a save/open succeeded.
    On timeout, inspect_windows then capture_window and continue the authorized
    task. Do not ask to restart solely for timeout or repeat an uncertain invoke.
    """
    from . import ui_access
    if action not in {"set_value", "invoke"} or len(value) > 4000:
        raise ValueError("Unsupported action or value too long")
    cfg = load_config()
    native = backend()
    with MOUSE_MUTEX:
        win = native.get_window(window_id, cfg["allowed"])
        verify_capture(capture_id, window_id, win.rect)
        if dry_run:
            return {"dry_run": True, "action": action, "automation_id": automation_id}
        require_session(cfg)
        native._activate(win)
        native._stop_if_needed()
        REGISTRY.consume(capture_id)
        if action == "set_value":
            actual = ui_access.value(win.hwnd, automation_id, value)
            return {"value_matches": actual == value, "notice": "Capture to verify UI"}
        ui_access.invoke(win.hwnd, automation_id)
        return {"invoke_requested": True, "notice": "Verify the resulting UI/file; invocation is not completion"}


@tool()
def app_control(window_id: str, capture_id: str, automation_id: str = "",
                action: Literal["set_value", "invoke"] = "invoke", value: str = "", dry_run: bool = True,
                control_name: str = "") -> dict:
    """Control supported app buttons/edits via UIA without SendInput or SetFocus.

    Shows a visual blue app cursor for visible controls. The app may change focus
    through its provider; report observed focus/pointer state and verify results.
    Unsupported canvas/drag controls fail; there is no physical-input fallback.
    """
    from . import ui_access, indicator
    if bool(automation_id)==bool(control_name) or len(control_name)>300 or action not in {"set_value", "invoke"} or len(value)>4000:
        raise ValueError("Exactly one unique automation_id or control_name, supported action and bounded value required")
    cfg=load_config()
    with MOUSE_MUTEX:
        native=require_session(cfg)
        win=native.get_window(window_id,cfg["allowed"])
        native.require_unblocked(win)
        verify_capture(capture_id,window_id,win.rect)
        controls=[c for c in ui_access.inspect(win.hwnd) if (c["automation_id"]==automation_id if automation_id else c["name"]==control_name)
                  and c["control_type"]==(50004 if action=="set_value" else 50000)]
        if len(controls)!=1 or not controls[0]["enabled"]:
            raise ValueError("Expected exactly one enabled control with this ID")
        if dry_run:return {"dry_run":True,"action":action,"physical_input":False}
        before=native.POINT()
        if not native.U.GetCursorPos(before):raise RuntimeError("Cannot inspect pointer position")
        foreground=native.U.GetForegroundWindow()
        indicator.ensure(native.SESSION_STOP)
        native._stop_if_needed()
        REGISTRY.consume(capture_id)
        rect=controls[0]["rect"]
        indicator.mark_target(win.hwnd,(rect[0]+rect[2])//2,(rect[1]+rect[3])//2)
        actual=ui_access.value(win.hwnd,automation_id,value,control_name=control_name) if action=="set_value" else ui_access.invoke(win.hwnd,automation_id,control_name=control_name)
        after=native.POINT()
        native.U.GetCursorPos(after)
        return {"physical_input":False,"value_matches":actual==value if action=="set_value" else None,
                "invoke_requested":action=="invoke","pointer_unchanged":(before.x,before.y)==(after.x,after.y),
                "focus_unchanged":foreground==native.U.GetForegroundWindow(),
                "notice":"App provider controls the result; verify the resulting UI/file"}


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
    native = backend()
    target = Path(path)
    if not target.is_absolute() or str(target).startswith("\\\\") or target.suffix.lower() != ".txt" or not target.parent.is_dir():
        raise ValueError("Existing local parent directory and absolute .txt path required")
    with MOUSE_MUTEX:
        win = native.get_window(window_id, cfg["allowed"])
        if win.exe != "notepad.exe":
            raise ValueError("This semantic save only supports classic Notepad")
        verify_capture(capture_id, window_id, win.rect)
        text = ui_access.value(win.hwnd, "15")
        if len(text) > 1_000_000:
            raise ValueError("Notepad buffer too large")
        if dry_run:
            return {"dry_run": True, "path": str(target), "characters": len(text)}
        require_session(cfg)
        REGISTRY.consume(capture_id)
        if target.exists():
            if target.read_text(encoding="utf-8-sig") != text:
                raise FileExistsError("Existing file differs; preserved without overwriting")
        else:
            with target.open("x", encoding="utf-8", newline="") as output:
                output.write(text)
        matches = target.read_text(encoding="utf-8-sig") == text
        if not matches:
            raise RuntimeError("Saved file verification failed")
        native._stop_if_needed()
        if open_saved:
            notepad = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/notepad.exe"
            subprocess.Popen([str(notepad), str(target)])
        return {"saved_verified": True, "path": str(target), "characters": len(text),
                "open_requested": open_saved, "method": "Notepad UIA buffer + UTF-8 file API; original remains open"}


@tool()
def show_live_view(window_id: str = "", source: Literal["window", "desktop"] = "window",
                   monitor_id: str = "all", fullscreen: bool = False) -> dict:
    """Show a local live preview of one allowed window. Esc closes and stops input.

    source=desktop supports one returned monitor_id or all monitors together.
    fullscreen=True fills the selected monitor(s); fullscreen is click-through
    so underlying application input still works. F11 toggles when preview has
    focus; call again to switch source/monitor/fullscreen without cancelling.
    Desktop preview requires all-app scope. Frames stay local until capture.
    A stopped session cannot be resumed by reopening or switching the preview.
    """
    from .viewer import show_viewer
    cfg = load_config()
    if cfg["mouse_control_mode"] == "foreground_session":
        native = require_session(cfg)
        from . import indicator
        indicator.ensure(native.SESSION_STOP)
    if source == "window":
        backend().get_window(window_id, cfg["allowed"])
    elif source == "desktop":
        if "*" not in cfg["allowed"]:
            raise PermissionError('Desktop preview requires owner-authorized all applications')
    else:
        raise ValueError('source must be window or desktop')
    with MOUSE_MUTEX:
        return show_viewer(window_id, cfg["allowed"], source, monitor_id, fullscreen)


@tool()
def close_live_view() -> dict:
    """Close the local preview and latch an emergency stop for physical input."""
    from .viewer import close_viewer
    close_viewer()
    return {"close_requested": True, "input_stopped": True}


@tool(structured_output=False)
def capture_window(window_id: str) -> CallToolResult:
    """Capture an allowlisted window WITHOUT focusing it, return PNG plus capture_id.

    GPU viewports may be blank; verify image visually before using coordinates.
    MCP screenshot bytes are transferred to the AI client, not solely kept local.
    After timeout, inspect_windows first. A successful fresh capture then clears
    the timeout observation gate, without clearing Esc/F12 or replaying input.
    """
    with MOUSE_MUTEX:
        return _capture_window_result(window_id)


def _capture_window_result(window_id: str) -> CallToolResult:
    observation = recovery.observation()
    cfg = load_config()
    win = backend().get_window(window_id, cfg["allowed"])
    png, method, blank = backend().capture_window(win)
    if blank:
        raise RuntimeError("PrintWindow returned a uniform/possibly blank image; NO click token issued")
    if recovery.captured(observation):
        # Invalidate atomically under MOUSE_MUTEX, before issuing this ticket.
        # Clock timestamps can be equal on Windows/Python 3.11; deleting old
        # tickets is reliable even with coarse timer resolution.
        REGISTRY.invalidate_all()
    t = REGISTRY.issue(win.id, win.rect, method)
    info = {"window_id": win.id, "capture_id": t.token,
            "width": win.rect.width, "height": win.rect.height,
            "method": method, "screenshot_verified_by_user": False,
            "note": "Coordinates are relative to OUTER window; may include borders. Screenshot may include sensitive content."}
    return CallToolResult(content=[
        TextContent(type="text", text=json.dumps(info, ensure_ascii=False)),
        ImageContent(type="image", mimeType="image/png", data=base64.b64encode(png).decode("ascii"))
    ])


def ask_local_consent(summary: str) -> bool:
    """Unspoofable via MCP args: operator must click Yes in a Windows dialog."""
    import ctypes as ct
    user32 = ct.WinDLL("user32", use_last_error=True)
    # YES/NO + warning icon + TOPMOST. UI intervention is mandatory for host mouse.
    result = user32.MessageBoxW(
        None,
        "MCP requested physical mouse control. Your mouse/focus will be occupied.\n\n"
        + summary + "\n\nAuthorize exactly this one finite operation?",
        "Win10 Bridge - local human confirmation",
        0x00000004 | 0x00000030 | 0x00040000
    )
    return result == 6  # IDYES


@tool()
def mouse_action(
    window_id: str,
    capture_id: str,
    action: Literal["move", "click", "double_click", "drag", "hold", "scroll"],
    x: int,
    y: int,
    button: Literal["left", "right", "middle", "x1", "x2"] = "left",
    end_x: int = -1,
    end_y: int = -1,
    duration_ms: int = 400,
    steps: int = 16,
    wheel_ticks: int = 1,
    wheel_axis: Literal["vertical", "horizontal"] = "vertical",
    modifiers: str = "",
    dry_run: bool = True,
) -> dict:
    """Physical mouse control with fresh screenshot + native human consent.

    action: move|click|double_click|drag|hold|scroll. button: left|right|middle|x1|x2.
    Drag holds the button through intermediate positions; hold has a bounded duration.
    wheel_axis: vertical|horizontal. modifiers: ctrl+shift+alt+space subset.
    DEFAULT dry_run=True. Owner-authorized foreground_session has no dialogs;
    legacy foreground_confirm_each asks for each action. Scroll sends no clicks.
    IMPORTANT: The host's real mouse and focus ARE shared while executing.
    """
    cfg = load_config()
    m = backend()
    mods = validate_mouse(action, button, duration_ms, steps, wheel_ticks, wheel_axis, modifiers)
    with MOUSE_MUTEX:
        win = m.get_window(window_id, cfg["allowed"])
        ex = x if end_x == -1 else end_x
        ey = y if end_y == -1 else end_y
        sx, sy = win.rect.absolute(x, y)
        tx, ty = win.rect.absolute(ex, ey)
        if action == "drag" and (ex, ey) == (x, y):
            raise ValueError("Drag must specify a different end point")
        verify_capture(capture_id, window_id, win.rect)
        summary = f"{win.exe} | {win.title[:80]}\n{action} {button} from {x},{y} to {ex},{ey} | {duration_ms} ms | wheel={wheel_ticks} {wheel_axis} | mods={mods}"
        if dry_run:
            return {"dry_run": True, "summary": summary,
                    "physical_coordinates": [[sx, sy], [tx, ty]],
                    "mouse_control_mode": cfg["mouse_control_mode"],
                    "note": "No input sent. Set dry_run=false after local owner enables mouse mode."}
        if cfg["mouse_control_mode"] == "disabled":
            raise PermissionError("Mouse disabled in local config; background capture still works")
        if cfg["mouse_control_mode"] == "foreground_session":
            m.enable_session_stop()
        if cfg["mouse_control_mode"] == "foreground_confirm_each" and not ask_local_consent(summary):
            return {"performed": False, "reason": "Owner declined local Windows consent"}
        refreshed = m.get_window(window_id, cfg["allowed"])
        verify_capture(capture_id, refreshed.id, refreshed.rect)
        REGISTRY.consume(capture_id)  # one use only; re-capture before next action
        m.apply_mouse(refreshed, action, button, x, y, ex, ey,
                      duration_ms, steps, wheel_ticks, wheel_axis, mods)
        return {"performed": True, "mouse_action": action,
                "notice": "Sent physical input; software result unverified. Capture again to verify."}


@tool()
def click_left(window_id: str, capture_id: str, x: int, y: int, dry_run: bool = True) -> dict:
    """Nhấp chuột TRÁI đúng một lần; không gửi nút phải/giữa hay lăn chuột."""
    return mouse_action(window_id, capture_id, "click", x, y, button="left", dry_run=dry_run)


@tool()
def click_right(window_id: str, capture_id: str, x: int, y: int, dry_run: bool = True) -> dict:
    """Nhấp chuột PHẢI đúng một lần để mở menu ngữ cảnh; không gửi nút khác."""
    return mouse_action(window_id, capture_id, "click", x, y, button="right", dry_run=dry_run)


@tool()
def click_middle(window_id: str, capture_id: str, x: int, y: int, dry_run: bool = True) -> dict:
    """Nhấp nút GIỮA đúng một lần; đây là nhấn nút, không phải lăn chuột."""
    return mouse_action(window_id, capture_id, "click", x, y, button="middle", dry_run=dry_run)


@tool()
def scroll_mouse(window_id: str, capture_id: str, x: int, y: int,
                 wheel_ticks: int = 1, wheel_axis: Literal["vertical", "horizontal"] = "vertical",
                 dry_run: bool = True) -> dict:
    """Chỉ LĂN CHUỘT dọc/ngang; không gửi nhấn/nhả bất kỳ nút chuột nào."""
    return mouse_action(window_id, capture_id, "scroll", x, y,
                        wheel_ticks=wheel_ticks, wheel_axis=wheel_axis, dry_run=dry_run)


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
    native = backend()
    with MOUSE_MUTEX:
        win = native.get_window(window_id, cfg["allowed"])
        verify_capture(capture_id, window_id, win.rect)
        summary = f"{win.exe} | {win.title[:80]}\nType {len(text)} characters (replace all={replace_all}): {text[:160]}"
        if dry_run:
            return {"dry_run": True, "summary": summary}
        if cfg["mouse_control_mode"] == "disabled":
            raise PermissionError("Physical input disabled in local config")
        if cfg["mouse_control_mode"] == "foreground_session":
            native.enable_session_stop()
        if cfg["mouse_control_mode"] == "foreground_confirm_each" and not ask_local_consent(summary):
            return {"performed": False, "reason": "Owner declined local Windows consent"}
        current = native.get_window(window_id, cfg["allowed"])
        verify_capture(capture_id, window_id, current.rect)
        REGISTRY.consume(capture_id)
        native.apply_text(current, text, replace_all=replace_all)
        return {"performed": True, "characters": len(text), "notice": "Capture again to verify editor contents"}


@tool()
def press_key(window_id: str, capture_id: str, key: str, dry_run: bool = True) -> dict:
    """Press one bounded key or chord, e.g. ctrl+s, ctrl+l, enter, tab, alt+n.

    Only listed keys are accepted; Windows/system keys and Esc are excluded.
    Physical Esc is reserved for stopping the authorized session.
    Capture and verify the resulting UI before the next action.
    """
    cfg = load_config()
    native = backend()
    parts = tuple(key.lower().split("+"))
    if not 1 <= len(parts) <= 4 or len(set(parts)) != len(parts) or any(k not in native.KEY_CODES for k in parts):
        raise ValueError("Unsupported key chord")
    if len(parts) > 1 and (any(k not in {"ctrl", "shift", "alt"} for k in parts[:-1]) or parts[-1] in {"ctrl", "shift", "alt"}):
        raise ValueError("Use modifier(s)+one key")
    with MOUSE_MUTEX:
        win = native.get_window(window_id, cfg["allowed"])
        verify_capture(capture_id, window_id, win.rect)
        if dry_run:
            return {"dry_run": True, "key": key, "window_id": window_id}
        if cfg["mouse_control_mode"] == "disabled":
            raise PermissionError("Physical input disabled in local config")
        if cfg["mouse_control_mode"] == "foreground_session":
            native.enable_session_stop()
        if cfg["mouse_control_mode"] == "foreground_confirm_each" and not ask_local_consent(f"{win.exe} | {win.title[:80]}\nPress {key}"):
            return {"performed": False, "reason": "Owner declined"}
        current = native.get_window(window_id, cfg["allowed"])
        verify_capture(capture_id, window_id, current.rect)
        REGISTRY.consume(capture_id)
        native.apply_keys(current, parts)
        return {"performed": True, "key": key, "notice": "Capture again to verify"}


@tool()
def list_drives() -> dict:
    """Read existing local drive roots, for choosing an Explorer destination."""
    import string
    return {"drives": [f"{letter}:\\" for letter in string.ascii_uppercase if Path(f"{letter}:\\").is_dir()]}


@tool()
def open_directory(path: str) -> dict:
    """Open an existing absolute local directory in Windows Explorer.

    Requires explorer.exe or all applications allowed and foreground_session mode.
    No files/executables/URLs/UNC destinations; Esc stops this action too.
    """
    cfg = load_config()
    if cfg["mouse_control_mode"] != "foreground_session" or not process_allowed("explorer.exe", cfg["allowed"]):
        raise PermissionError("Owner must enable foreground_session and allow explorer.exe or all applications")
    target = Path(path)
    if not target.is_absolute() or str(target).startswith("\\\\") or not target.is_dir():
        raise ValueError("Existing absolute local directory required")
    native = backend()
    native.enable_session_stop()
    native._stop_if_needed()
    recovery.require_ready()
    os.startfile(str(target.resolve()))
    return {"open_requested": True, "path": str(target.resolve()), "notice": "Inspect windows and capture Explorer to verify"}


@tool()
def emergency_release() -> dict:
    """Best-effort release of any injected mouse buttons and modifiers; no dialog."""
    backend().SESSION_STOP.set()
    backend().release_all()
    return {"released": True, "note": "Best-effort; Esc/F12 interrupts physical actions"}


def main() -> None:
    # Read config at startup so malformed settings fail fast.
    cfg = load_config()
    if cfg["mouse_control_mode"] == "foreground_session":
        backend().enable_session_stop()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
