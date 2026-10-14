"""Exclude bridge authorization UI from automation and serialize desktop pixels.

The named mutex prevents an authorization/credential surface appearing during
a desktop capture. Properties protect its own/owned windows from target APIs.
"""
from contextlib import contextmanager
import ctypes as ct
from ctypes import wintypes as wt
import sys

PROPERTY = "TaskKit.OwnerAuthorizationSurface.v1"
MUTEX = "Local\\TaskKit.OwnerAuthorizationAndDesktopCapture.v1"


def protected_target(api, hwnd):
    current = api.root(hwnd)
    seen = set()
    for _ in range(64):
        if not current:
            return False
        if current in seen:
            raise PermissionError("Invalid window owner chain")
        seen.add(current)
        if api.marked(current):
            return True
        current = api.owner(current)
    raise PermissionError("Window owner chain exceeds safety limit")


class SurfaceAPI:
    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Owner surface protection requires Windows")
        self.u = ct.WinDLL("user32", use_last_error=True)
        self.u.GetAncestor.argtypes = (wt.HWND, wt.UINT)
        self.u.GetAncestor.restype = wt.HWND
        self.u.GetWindow.argtypes = (wt.HWND, wt.UINT)
        self.u.GetWindow.restype = wt.HWND
        self.u.GetPropW.argtypes = (wt.HWND, wt.LPCWSTR)
        self.u.GetPropW.restype = wt.HANDLE
        self.u.SetPropW.argtypes = (wt.HWND, wt.LPCWSTR, wt.HANDLE)
        self.u.SetPropW.restype = wt.BOOL

    def root(self, hwnd): return int(self.u.GetAncestor(hwnd, 2) or 0)
    def owner(self, hwnd): return int(self.u.GetWindow(hwnd, 4) or 0)
    def marked(self, hwnd): return bool(self.u.GetPropW(hwnd, PROPERTY))


def assert_not_owner_surface(hwnd):
    if protected_target(SurfaceAPI(), hwnd):
        raise PermissionError("Bridge owner authorization UI is protected from capture/input/UIA")


def mark_owner_surface(widget):
    widget.update_idletasks()
    mark_owner_hwnd(widget.winfo_id())


def mark_owner_hwnd(hwnd):
    api = SurfaceAPI()
    root = api.root(hwnd)
    if not root or not api.u.SetPropW(root, PROPERTY, wt.HANDLE(1)):
        raise ct.WinError(ct.get_last_error())


@contextmanager
def protected_consent_window():
    """Native hidden owner for MessageBox; owned dialogs inherit protection."""
    with desktop_surface_barrier(owner=True):
        api = SurfaceAPI()
        u = api.u
        u.CreateWindowExW.argtypes = (wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                     ct.c_int, ct.c_int, ct.c_int, ct.c_int,
                                     wt.HWND, wt.HANDLE, wt.HANDLE, ct.c_void_p)
        u.CreateWindowExW.restype = wt.HWND
        u.DestroyWindow.argtypes = (wt.HWND,)
        owner = u.CreateWindowExW(0, "STATIC", "TaskKit local owner consent", 0x80000000,
                                 0, 0, 0, 0, None, None, None, None)
        if not owner:
            raise ct.WinError(ct.get_last_error())
        try:
            mark_owner_hwnd(owner)
            yield owner
        finally:
            u.DestroyWindow(owner)


@contextmanager
def desktop_surface_barrier(*, owner=False):
    if sys.platform != "win32":
        raise OSError("Desktop permission barrier requires Windows")
    k = ct.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.argtypes = (ct.c_void_p, wt.BOOL, wt.LPCWSTR)
    k.CreateMutexW.restype = wt.HANDLE
    k.WaitForSingleObject.argtypes = (wt.HANDLE, wt.DWORD)
    k.WaitForSingleObject.restype = wt.DWORD
    k.ReleaseMutex.argtypes = (wt.HANDLE,)
    k.CloseHandle.argtypes = (wt.HANDLE,)
    handle = k.CreateMutexW(None, False, MUTEX)
    if not handle:
        raise ct.WinError(ct.get_last_error())
    acquired = False
    try:
        result = k.WaitForSingleObject(handle, 1000 if owner else 0)
        acquired = result in {0, 0x80}
        if result != 0:
            raise PermissionError("Owner permission UI and desktop capture cannot run together; close/retry locally")
        yield
    finally:
        if acquired:
            k.ReleaseMutex(handle)
        k.CloseHandle(handle)
