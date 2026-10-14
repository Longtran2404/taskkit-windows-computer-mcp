"""Win32 backend. Imported only on Windows by the MCP server.

NO shell invocation, networking, binary patching, or background input hacks.
PrintWindow is best-effort; GPU/accelerated windows may not render correctly.
"""
from __future__ import annotations

import ctypes as ct
from ctypes import wintypes as wt
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import sys
import time
import threading

from PIL import Image as PILImage
from .policy import Rect, MAX_CAPTURE_PIXELS

if sys.platform != "win32":
    raise RuntimeError("Windows 10/11 interactive desktop required")

U = ct.WinDLL("user32", use_last_error=True)
K = ct.WinDLL("kernel32", use_last_error=True)
G = ct.WinDLL("gdi32", use_last_error=True)

# Refuse coordinate operations unless the active thread is per-monitor aware.
# A pre-existing incompatible host awareness must not silently virtualize pixels.
U.SetProcessDpiAwarenessContext.argtypes = (ct.c_void_p,)
U.SetProcessDpiAwarenessContext.restype = wt.BOOL
U.SetProcessDpiAwarenessContext(ct.c_void_p(-4))
U.GetThreadDpiAwarenessContext.argtypes = ()
U.GetThreadDpiAwarenessContext.restype = ct.c_void_p
U.GetAwarenessFromDpiAwarenessContext.argtypes = (ct.c_void_p,)
U.GetAwarenessFromDpiAwarenessContext.restype = ct.c_int
U.GetDpiForWindow.argtypes = (wt.HWND,)
U.GetDpiForWindow.restype = wt.UINT
K.GetDriveTypeW.argtypes = (wt.LPCWSTR,)
K.GetDriveTypeW.restype = wt.UINT


def _require_physical_mapping():
    if U.GetAwarenessFromDpiAwarenessContext(U.GetThreadDpiAwarenessContext()) != 2:
        raise RuntimeError("Per-monitor DPI awareness unavailable; refusing coordinate mapping")


def local_path(path: Path, *, directory=False) -> Path:
    from .policy import require_local_windows_path
    _stop_if_needed()
    if not path.is_absolute():
        raise ValueError("Absolute local path required")
    require_local_windows_path(str(path), 3)  # Shape check before filesystem access.
    require_local_windows_path(str(path), K.GetDriveTypeW(path.anchor))
    resolved = path.resolve(strict=True) if directory or path.exists() else path.parent.resolve(strict=True) / path.name
    require_local_windows_path(str(resolved), K.GetDriveTypeW(resolved.anchor))
    _stop_if_needed()
    return resolved

class RECT(ct.Structure):
    _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]

class POINT(ct.Structure):
    _fields_ = [("x", wt.LONG), ("y", wt.LONG)]

class BITMAPINFOHEADER(ct.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]

class BITMAPINFO(ct.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]

class MOUSEINPUT(ct.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ct.c_void_p)]

class KEYBDINPUT(ct.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ct.c_void_p)]

class INPUTUNION(ct.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

class INPUT(ct.Structure):
    _fields_ = [("type", wt.DWORD), ("payload", INPUTUNION)]

WINFUNCTYPE = ct.WINFUNCTYPE
WNDENUMPROC = WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

U.EnumWindows.argtypes = (WNDENUMPROC, wt.LPARAM)
U.EnumWindows.restype = wt.BOOL
U.IsWindowVisible.argtypes = (wt.HWND,)
U.IsWindowVisible.restype = wt.BOOL
U.IsIconic.argtypes = (wt.HWND,)
U.IsIconic.restype = wt.BOOL
U.GetWindowRect.argtypes = (wt.HWND, ct.POINTER(RECT))
U.GetWindowRect.restype = wt.BOOL
U.GetWindowTextLengthW.argtypes = (wt.HWND,)
U.GetWindowTextLengthW.restype = ct.c_int
U.GetWindowTextW.argtypes = (wt.HWND, wt.LPWSTR, ct.c_int)
U.GetWindowTextW.restype = ct.c_int
U.GetWindowThreadProcessId.argtypes = (wt.HWND, ct.POINTER(wt.DWORD))
U.GetWindowThreadProcessId.restype = wt.DWORD
U.PrintWindow.argtypes = (wt.HWND, wt.HDC, wt.UINT)
U.PrintWindow.restype = wt.BOOL
U.GetForegroundWindow.argtypes = ()
U.GetForegroundWindow.restype = wt.HWND
U.SetForegroundWindow.argtypes = (wt.HWND,)
U.SetForegroundWindow.restype = wt.BOOL
U.SetCursorPos.argtypes = (ct.c_int, ct.c_int)
U.SetCursorPos.restype = wt.BOOL
U.GetCursorPos.argtypes = (ct.POINTER(POINT),)
U.GetCursorPos.restype = wt.BOOL
U.SendInput.argtypes = (wt.UINT, ct.POINTER(INPUT), ct.c_int)
U.SendInput.restype = wt.UINT
U.GetAsyncKeyState.argtypes = (ct.c_int,)
U.GetAsyncKeyState.restype = wt.SHORT
U.WindowFromPoint.argtypes = (POINT,)
U.WindowFromPoint.restype = wt.HWND
U.GetAncestor.argtypes = (wt.HWND, wt.UINT)
U.GetAncestor.restype = wt.HWND

K.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
K.OpenProcess.restype = wt.HANDLE
K.CloseHandle.argtypes = (wt.HANDLE,)
K.CloseHandle.restype = wt.BOOL
K.QueryFullProcessImageNameW.argtypes = (wt.HANDLE, wt.DWORD, wt.LPWSTR, ct.POINTER(wt.DWORD))
K.QueryFullProcessImageNameW.restype = wt.BOOL
G.CreateCompatibleDC.argtypes = (wt.HDC,)
G.CreateCompatibleDC.restype = wt.HDC
G.DeleteDC.argtypes = (wt.HDC,)
G.DeleteDC.restype = wt.BOOL
G.CreateDIBSection.argtypes = (wt.HDC, ct.POINTER(BITMAPINFO), wt.UINT, ct.POINTER(ct.c_void_p), wt.HANDLE, wt.DWORD)
G.CreateDIBSection.restype = wt.HBITMAP
G.DeleteObject.argtypes = (wt.HGDIOBJ,)
G.DeleteObject.restype = wt.BOOL
G.SelectObject.argtypes = (wt.HDC, wt.HGDIOBJ)
G.SelectObject.restype = wt.HGDIOBJ

K.GetProcessTimes.argtypes = (wt.HANDLE, ct.POINTER(wt.FILETIME), ct.POINTER(wt.FILETIME),
                              ct.POINTER(wt.FILETIME), ct.POINTER(wt.FILETIME))
K.GetProcessTimes.restype = wt.BOOL

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSE_LEFT_DOWN, MOUSE_LEFT_UP = 0x0002, 0x0004
MOUSE_RIGHT_DOWN, MOUSE_RIGHT_UP = 0x0008, 0x0010
MOUSE_MIDDLE_DOWN, MOUSE_MIDDLE_UP = 0x0020, 0x0040
MOUSE_X_DOWN, MOUSE_X_UP = 0x0080, 0x0100
MOUSE_WHEEL, MOUSE_HWHEEL = 0x0800, 0x1000
BUTTON_FLAGS = {
    "left": (MOUSE_LEFT_DOWN, MOUSE_LEFT_UP, 0),
    "right": (MOUSE_RIGHT_DOWN, MOUSE_RIGHT_UP, 0),
    "middle": (MOUSE_MIDDLE_DOWN, MOUSE_MIDDLE_UP, 0),
    "x1": (MOUSE_X_DOWN, MOUSE_X_UP, 1),
    "x2": (MOUSE_X_DOWN, MOUSE_X_UP, 2),
}
SESSION_STOP = threading.Event()
_session_watcher = None
_session_lock = threading.Lock()


def latch_stop():
    """One-way parent stop also closes the shared preview event and its workers."""
    SESSION_STOP.set()
    from .viewer import close_viewer
    close_viewer()


def enable_session_stop() -> None:
    """Start a stop watcher in any mode; this never grants input authorization."""
    global _session_watcher
    with _session_lock:
        if _session_watcher is not None:
            return  # Never clear a stopped session remotely.
        if U.GetAsyncKeyState(0x1B) & 0x8000 or U.GetAsyncKeyState(0x7B) & 0x8000:
            latch_stop()
        def watch():
            while not SESSION_STOP.is_set():
                from .viewer import stopped
                if stopped() or U.GetAsyncKeyState(0x1B) & 0x8001 or U.GetAsyncKeyState(0x7B) & 0x8001:
                    latch_stop()
                    return
                SESSION_STOP.wait(0.02)
        _session_watcher = threading.Thread(target=watch, daemon=True)
        _session_watcher.start()


@dataclass(frozen=True)
class Window:
    hwnd: int
    pid: int
    exe: str
    title: str
    rect: Rect
    created: int
    dpi: int

    @property
    def id(self) -> str:
        return f"{self.pid}:{self.hwnd:x}:{self.created:x}"


def process_identity(pid: int) -> tuple[str, int] | None:
    handle = K.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ct.create_unicode_buffer(32768)
        n = wt.DWORD(len(buf))
        created, exited, kernel, user = (wt.FILETIME() for _ in range(4))
        if (K.QueryFullProcessImageNameW(handle, 0, buf, ct.byref(n)) and
                K.GetProcessTimes(handle, ct.byref(created), ct.byref(exited), ct.byref(kernel), ct.byref(user))):
            return Path(buf.value).name.lower(), (created.dwHighDateTime << 32) | created.dwLowDateTime
    finally:
        K.CloseHandle(handle)
    return None


def _read_window(hwnd: int, allowed: frozenset[str]) -> Window:
    _require_physical_mapping()
    if not U.IsWindowVisible(hwnd) or U.IsIconic(hwnd):
        raise ValueError("Window missing or minimized")
    pid = wt.DWORD()
    U.GetWindowThreadProcessId(hwnd, ct.byref(pid))
    identity = process_identity(pid.value)
    if not identity or identity[0] not in allowed:
        raise PermissionError("Process identity missing or not allowed")
    rect = RECT()
    if not U.GetWindowRect(hwnd, ct.byref(rect)):
        raise OSError("GetWindowRect failed")
    r = Rect(rect.left, rect.top, rect.right, rect.bottom)
    dpi = int(U.GetDpiForWindow(hwnd))
    if r.width < 100 or r.height < 80 or r.width * r.height > MAX_CAPTURE_PIXELS or not dpi:
        raise ValueError("Unsupported window geometry or DPI")
    n = min(U.GetWindowTextLengthW(hwnd), 1000)
    buf = ct.create_unicode_buffer(n + 2)
    U.GetWindowTextW(hwnd, buf, len(buf))
    return Window(hwnd, pid.value, identity[0], buf.value, r, identity[1], dpi)


def enumerate_windows(allowed: frozenset[str]) -> list[Window]:
    _stop_if_needed()
    _require_physical_mapping()
    found = []
    callback_errors = []
    def check(hwnd, _):
        try:
            _stop_if_needed()
            win = _read_window(hwnd, allowed)
            if win.title:
                found.append(win)
        except (ValueError, PermissionError, OSError):
            pass
        except Exception as exc:
            # Never let ctypes silently swallow stop/DPI errors in its callback.
            callback_errors.append(exc)
            return False
        return True
    success = U.EnumWindows(WNDENUMPROC(check), 0)
    if callback_errors:
        raise callback_errors[0]
    if not success:
        raise OSError("EnumWindows failed")
    _stop_if_needed()
    return found


def get_window(window_id: str, allowed: frozenset[str]) -> Window:
    _stop_if_needed()
    try:
        parts = window_id.split(":")
        if len(parts) != 3:
            raise ValueError
        win = _read_window(int(parts[1], 16), allowed)
    except (ValueError, OSError) as exc:
        raise ValueError("Invalid/missing window; inspect windows again") from exc
    if win.id != window_id:
        raise ValueError("Window process identity changed; inspect windows again")
    _stop_if_needed()
    return win


def check_window(win: Window, *, foreground=False):
    _stop_if_needed()
    current = get_window(win.id, frozenset({win.exe}))
    if current.rect != win.rect or current.dpi != win.dpi:
        raise RuntimeError("Window geometry/DPI changed; capture again")
    if foreground and U.GetForegroundWindow() != win.hwnd:
        raise RuntimeError("Target lost foreground focus; input aborted")
    _stop_if_needed()
    return current


def _native_job(payload, cancel):
    global _worker_cancel, _worker_deadline
    _worker_cancel = cancel
    operation, win, args, _worker_deadline = payload
    check_window(win, foreground=operation not in {"capture", "inspect", "value_read"})
    if operation == "capture":
        result = _capture_direct(win)
    else:
        from . import ui_access
        guard = lambda: check_window(win, foreground=operation not in {"inspect", "value_read"})
        result = ui_access._dispatch(operation, win.hwnd, args, guard)
    check_window(win, foreground=operation not in {"capture", "inspect", "value_read"})
    return result


def capture_window(win: Window):
    from .bounded_worker import run
    try:
        return run(_native_job, ("capture", win, (), None), timeout=3.0,
                   guard=lambda: check_window(win), on_unreaped=latch_stop)
    except InterruptedError:
        latch_stop()
        raise


def _capture_direct(win: Window) -> tuple[bytes, str, bool]:
    """Capture via PrintWindow; never fallback to occlusion-prone desktop pixels.

    Returns PNG bytes, capture method, suspicious/mostly uniform flag.
    """
    if win.rect.width * win.rect.height > MAX_CAPTURE_PIXELS:
        raise ValueError("Refusing oversized capture")
    info = BITMAPINFO()
    info.bmiHeader.biSize = ct.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = win.rect.width
    info.bmiHeader.biHeight = -win.rect.height  # top-down BGRA
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0  # BI_RGB
    memdc = G.CreateCompatibleDC(None)
    if not memdc:
        raise OSError("CreateCompatibleDC failed")
    bitmap = None
    prev = None
    try:
        pixelptr = ct.c_void_p()
        bitmap = G.CreateDIBSection(memdc, ct.byref(info), 0, ct.byref(pixelptr), None, 0)
        if not bitmap or not pixelptr.value:
            raise OSError("CreateDIBSection failed")
        prev = G.SelectObject(memdc, bitmap)
        if not prev:
            raise OSError("SelectObject failed")
        render_method = ""
        for flag, label in [(2, "PrintWindow full"), (0, "PrintWindow basic")]:
            ct.memset(pixelptr, 0, win.rect.width * win.rect.height * 4)
            check_window(win)
            if U.PrintWindow(win.hwnd, memdc, flag):
                render_method = label
                break
        if not render_method:
            raise RuntimeError("PrintWindow failed for this app. GPU viewport may be unsupported.")
        pixels = ct.string_at(pixelptr, win.rect.width * win.rect.height * 4)
        im = PILImage.frombytes("RGBA", (win.rect.width, win.rect.height), pixels, "raw", "BGRA")
        rgb = im.convert("RGB")
        # A basic blank-frame guard, not visual correctness certification.
        tiny = rgb.resize((64, 64))
        extrema = tiny.getextrema()
        possibly_blank = all(hi - lo < 8 for lo, hi in extrema)
        out = BytesIO()
        rgb.save(out, format="PNG", optimize=True)
        check_window(win)
        return out.getvalue(), render_method, possibly_blank
    finally:
        if prev:
            G.SelectObject(memdc, prev)
        if bitmap:
            G.DeleteObject(bitmap)
        G.DeleteDC(memdc)


def _send(inp: INPUT) -> None:
    result = U.SendInput(1, ct.byref(inp), ct.sizeof(INPUT))
    if result != 1:
        raise OSError(f"SendInput failed. Error={ct.get_last_error()}; UIPI may block elevated target")


def _mouse(flags: int, data: int = 0) -> None:
    inp = INPUT(type=INPUT_MOUSE)
    inp.payload.mi.dwFlags = flags
    inp.payload.mi.mouseData = data & 0xffffffff
    _send(inp)


def _virtual_key(vk: int, is_down: bool) -> None:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.payload.ki.wVk = vk
    inp.payload.ki.dwFlags = 0 if is_down else KEYEVENTF_KEYUP
    _send(inp)


def _position(x: int, y: int) -> None:
    if not U.SetCursorPos(int(x), int(y)):
        raise OSError(f"SetCursorPos failed: {ct.get_last_error()}")


def _verify_hit(win: Window, x: int, y: int) -> None:
    point = POINT()
    if not U.GetCursorPos(ct.byref(point)):
        raise OSError("GetCursorPos failed before hit test")
    if (point.x, point.y) != (x, y):
        raise InterruptedError("Actual cursor differs from intended point; refusing input")
    hit = U.WindowFromPoint(point)
    if not hit or U.GetAncestor(hit, 2) != win.hwnd:
        raise RuntimeError("Point is covered by another window; refusing input")


KEY_CODES = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "enter": 0x0D,
             "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E,
             "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
             "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
             **{chr(c).lower(): c for c in range(65, 91)},
             **{str(c): ord(str(c)) for c in range(10)}}


_worker_cancel = None
_worker_deadline = None


def _stop_if_needed() -> None:
    from .viewer import stopped
    if U.GetAsyncKeyState(0x1B) & 0x8001 or U.GetAsyncKeyState(0x7B) & 0x8001 or stopped():
        latch_stop()
    if SESSION_STOP.is_set() or (_worker_cancel is not None and _worker_cancel.is_set()):
        raise InterruptedError("Permanent Esc/F12/preview stop; restart locally to resume")
    if _worker_deadline is not None and time.monotonic() >= _worker_deadline:
        raise PermissionError("Local consent expired during UIA operation")


def _interruptible_wait(seconds, win=None):
    end = time.monotonic() + seconds
    while True:
        _stop_if_needed()
        if win is not None:
            check_window(win)
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        SESSION_STOP.wait(min(0.01, remaining))


def _activate(win):
    check_window(win)
    if U.GetForegroundWindow() != win.hwnd:
        U.SetForegroundWindow(win.hwnd)
        _interruptible_wait(0.10, win)
    check_window(win, foreground=True)


class NativeAdapter:
    key_codes = KEY_CODES

    def __init__(self, guard=lambda: None):
        self.authorization_guard = guard

    def check(self, win, *, foreground=True):
        self.authorization_guard()
        check_window(win, foreground=foreground)

    def activate(self, win):
        _activate(win)

    def cursor(self):
        point = POINT()
        if not U.GetCursorPos(ct.byref(point)):
            raise OSError("GetCursorPos failed")
        return point.x, point.y

    def held_inputs(self):
        # Include both sides of modifiers and system keys; do not alter user input.
        # Reserved stop keys belong to the stop watcher; do not consume their
        # recent-press bits while scanning ordinary held input.
        return {vk for vk in range(1, 256) if vk not in {0x1B, 0x7B}
                and U.GetAsyncKeyState(vk) & 0x8000}

    def code(self, kind, value):
        if kind == "button":
            return {{"left": 1, "right": 2, "middle": 4, "x1": 5, "x2": 6}[value]}
        if kind == "unicode":
            return {0xE7}
        return {0x11: {0x11, 0xA2, 0xA3}, 0x10: {0x10, 0xA0, 0xA1},
                0x12: {0x12, 0xA4, 0xA5}}.get(value, {value})

    def emit(self, kind, value, down):
        if kind == "button":
            flags = BUTTON_FLAGS[value]
            _mouse(flags[0 if down else 1], flags[2])
        elif kind == "key":
            _virtual_key(value, down)
        else:
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.payload.ki.wScan = value
            inp.payload.ki.dwFlags = KEYEVENTF_UNICODE | (0 if down else KEYEVENTF_KEYUP)
            _send(inp)

    def position(self, x, y):
        _position(x, y)

    def verify_hit(self, win, x, y):
        _verify_hit(win, x, y)

    def wait(self, seconds):
        SESSION_STOP.wait(seconds)

    def wheel(self, axis, amount):
        _mouse(MOUSE_WHEEL if axis == "vertical" else MOUSE_HWHEEL, amount)


def apply_keys(win, keys, *, guard=lambda: None):
    from .input_transaction import keys as perform
    perform(NativeAdapter(guard), win, keys)


def apply_text(win, text, replace_all=False, *, guard=lambda: None):
    from .input_transaction import text as perform
    perform(NativeAdapter(guard), win, text, replace_all)


def apply_mouse(win, *args, guard=lambda: None):
    from .input_transaction import mouse as perform
    perform(NativeAdapter(guard), win, *args)


def release_all():
    """Explicit emergency only: broad best-effort ups may affect owner-held input."""
    failures = []
    for button in BUTTON_FLAGS:
        try:
            _mouse(BUTTON_FLAGS[button][1], BUTTON_FLAGS[button][2])
        except Exception:
            failures.append(button)
    for vk in set(KEY_CODES.values()):
        try:
            _virtual_key(vk, False)
        except Exception:
            failures.append(str(vk))
    return failures
