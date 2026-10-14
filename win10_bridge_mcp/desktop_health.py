"""Read-only interactive context diagnostics; never switch desktop/session."""
import ctypes as ct
from ctypes import wintypes as wt
import os
import sys


def classify_context(snapshot):
    result = dict(snapshot)
    matched = (bool(snapshot.get("thread_desktop")) and
               snapshot.get("thread_desktop") == snapshot.get("input_desktop"))
    interactive = (matched and snapshot.get("window_station") == "WinSta0" and
                   snapshot.get("process_session_id") not in {None, 0} and bool(snapshot.get("foreground_hwnd")))
    result.update(desktop_match=matched, usable_interactive_context=interactive,
                  live_operations_verified=False, automatically_switches_desktop=False)
    if interactive:
        result["status"] = "owner_input_desktop_detected"
    elif snapshot.get("thread_desktop") and snapshot.get("input_desktop") and not matched:
        result["status"] = "desktop_mismatch"
    else:
        result["status"] = "interactive_context_unavailable_or_unverified"
    result["next_step"] = ("Run the bridge from the owner's interactive desktop using the authorized host. "
                           "A grant does not move it out of a sandbox desktop. No elevation/service/desktop switching is performed.")
    return result


def desktop_health():
    if sys.platform != "win32":
        return classify_context({"platform": sys.platform})
    k = ct.WinDLL("kernel32", use_last_error=True)
    u = ct.WinDLL("user32", use_last_error=True)
    k.GetCurrentThreadId.restype = wt.DWORD
    k.ProcessIdToSessionId.argtypes = (wt.DWORD, ct.POINTER(wt.DWORD))
    k.WTSGetActiveConsoleSessionId.restype = wt.DWORD
    u.GetThreadDesktop.argtypes = (wt.DWORD,)
    u.GetThreadDesktop.restype = wt.HANDLE
    u.GetProcessWindowStation.restype = wt.HANDLE
    u.OpenInputDesktop.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
    u.OpenInputDesktop.restype = wt.HANDLE
    u.CloseDesktop.argtypes = (wt.HANDLE,)
    u.GetForegroundWindow.restype = wt.HWND
    u.GetUserObjectInformationW.argtypes = (wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD, ct.POINTER(wt.DWORD))

    def name(handle):
        needed = wt.DWORD()
        if not handle:
            return None
        u.GetUserObjectInformationW(handle, 2, None, 0, ct.byref(needed))
        if not 0 < needed.value <= 65536:
            return None
        buffer = ct.create_unicode_buffer((needed.value + ct.sizeof(ct.c_wchar) - 1) // ct.sizeof(ct.c_wchar))
        if not u.GetUserObjectInformationW(handle, 2, buffer, ct.sizeof(buffer), ct.byref(needed)):
            return None
        return buffer.value

    session = wt.DWORD()
    if not k.ProcessIdToSessionId(os.getpid(), ct.byref(session)):
        raise ct.WinError(ct.get_last_error())
    console = k.WTSGetActiveConsoleSessionId()
    input_desktop = u.OpenInputDesktop(0, False, 1)
    try:
        snapshot = {"platform": "win32", "process_session_id": session.value,
                    "console_session_id": console if console != 0xFFFFFFFF else None,
                    "window_station": name(u.GetProcessWindowStation()),
                    "thread_desktop": name(u.GetThreadDesktop(k.GetCurrentThreadId())),
                    "input_desktop": name(input_desktop),
                    "foreground_hwnd": int(u.GetForegroundWindow() or 0)}
    finally:
        if input_desktop:
            u.CloseDesktop(input_desktop)
    return classify_context(snapshot)
