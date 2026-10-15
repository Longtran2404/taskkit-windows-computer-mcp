"""Desktop capture and monitor geometry. Never injects input or changes focus."""
from __future__ import annotations

from io import BytesIO
from .policy import Rect

MAX_DESKTOP_PIXELS = 40_000_000


def monitor_bounds(monitors: list[dict], monitor_id: str = 'all') -> Rect:
    selected = monitors if monitor_id == 'all' else [m for m in monitors if m['monitor_id'] == monitor_id]
    if not selected:
        raise ValueError('Unknown monitor_id; call list_monitors again')
    result = Rect(min(m['x'] for m in selected), min(m['y'] for m in selected),
                  max(m['x'] + m['width'] for m in selected), max(m['y'] + m['height'] for m in selected))
    if result.width <= 0 or result.height <= 0 or result.width * result.height > MAX_DESKTOP_PIXELS:
        raise ValueError('Desktop geometry exceeds the supported capture size')
    return result


def list_monitors() -> list[dict]:
    from . import windows_native as n
    ct, wt, u = n.ct, n.wt, n.U
    class INFO(ct.Structure):
        _fields_ = [('size', wt.DWORD), ('monitor', n.RECT), ('work', n.RECT), ('flags', wt.DWORD)]
    u.GetMonitorInfoW.argtypes = (wt.HANDLE, ct.POINTER(INFO))
    u.GetMonitorInfoW.restype = wt.BOOL
    callback = ct.WINFUNCTYPE(wt.BOOL, wt.HANDLE, wt.HDC, ct.POINTER(n.RECT), wt.LPARAM)
    found = []
    @callback
    def collect(handle, _, rect, __):
        info = INFO(); info.size = ct.sizeof(INFO)
        if not u.GetMonitorInfoW(handle, ct.byref(info)):
            return True
        r = rect.contents
        found.append({'x': r.left, 'y': r.top, 'width': r.right-r.left,
                      'height': r.bottom-r.top, 'primary': bool(info.flags & 1)})
        return True
    u.EnumDisplayMonitors.argtypes = (wt.HDC, ct.c_void_p, callback, wt.LPARAM)
    u.EnumDisplayMonitors.restype = wt.BOOL
    if not u.EnumDisplayMonitors(None, None, collect, 0) or not found:
        raise RuntimeError('No interactive monitors available')
    found.sort(key=lambda m: (not m['primary'], m['x'], m['y']))
    return [dict(m, monitor_id=f'monitor-{i+1}') for i, m in enumerate(found)]


def capture(monitor_id: str = 'all', max_edge: int = 4096) -> tuple[bytes, dict]:
    from PIL import ImageGrab, Image
    if not 640 <= max_edge <= 8192:
        raise ValueError('max_edge must be 640..8192')
    monitors = list_monitors()
    bounds = monitor_bounds(monitors, monitor_id)
    image = ImageGrab.grab(bbox=(bounds.left, bounds.top, bounds.right, bounds.bottom),
                           all_screens=True, include_layered_windows=True).convert('RGB')
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    out = BytesIO(); image.save(out, format='PNG')
    meta = {'monitor_id': monitor_id, 'monitors': monitors,
            'origin_x': bounds.left, 'origin_y': bounds.top,
            'desktop_width': bounds.width, 'desktop_height': bounds.height,
            'image_width': image.width, 'image_height': image.height,
            'scale_x': image.width/bounds.width, 'scale_y': image.height/bounds.height,
            'method': 'visible desktop, all_screens=True',
            'note': 'Visible pixels include dialogs. No input capture_id issued; inspect and capture the target window before input.'}
    return out.getvalue(), meta


def configure_preview(hwnd: int, fullscreen: bool, bounds: Rect, desktop_source: bool) -> dict:
    from . import windows_native as n
    ct, wt, u = n.ct, n.wt, n.U
    u.SetPropW.argtypes = (wt.HWND, wt.LPCWSTR, wt.HANDLE)
    u.SetPropW.restype = wt.BOOL
    u.SetWindowDisplayAffinity.argtypes = (wt.HWND, wt.DWORD)
    u.SetWindowDisplayAffinity.restype = wt.BOOL
    u.SetWindowPos.argtypes = (wt.HWND, wt.HWND, ct.c_int, ct.c_int, ct.c_int, ct.c_int, wt.UINT)
    u.SetWindowPos.restype = wt.BOOL
    u.GetWindowLongPtrW.argtypes = (wt.HWND, ct.c_int)
    u.GetWindowLongPtrW.restype = ct.c_ssize_t
    u.SetWindowLongPtrW.argtypes = (wt.HWND, ct.c_int, ct.c_ssize_t)
    u.SetWindowLongPtrW.restype = ct.c_ssize_t
    u.EnableWindow.argtypes = (wt.HWND, wt.BOOL)
    u.EnableWindow.restype = wt.BOOL
    u.SetLayeredWindowAttributes.argtypes = (wt.HWND, wt.DWORD, wt.BYTE, wt.DWORD)
    u.SetLayeredWindowAttributes.restype = wt.BOOL
    u.SetPropW(hwnd, 'TaskKitMCP.InternalView', 1)
    excluded = bool(u.SetWindowDisplayAffinity(hwnd, 0x11))
    if desktop_source and not excluded:
        raise RuntimeError('Windows could not exclude the preview from capture; desktop preview refused to avoid recursive capture')
    style = u.GetWindowLongPtrW(hwnd, -20)
    flags = 0x80000 | 0x20 | 0x08000000
    u.SetWindowLongPtrW(hwnd, -20, (style | flags) if fullscreen else (style & ~flags))
    if fullscreen:
        if not u.SetLayeredWindowAttributes(hwnd, 0, 255, 2):
            raise RuntimeError('Cannot configure fullscreen preview transparency')
        u.EnableWindow(hwnd, False)
        if not u.SetWindowPos(hwnd, -1, bounds.left, bounds.top, bounds.width, bounds.height, 0x10 | 0x20 | 0x40):
            raise RuntimeError('Cannot place fullscreen preview on selected monitors')
    else:
        u.EnableWindow(hwnd, True)
        u.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x1 | 0x2 | 0x10 | 0x20)
    actual = n.RECT()
    if not u.GetWindowRect(hwnd, ct.byref(actual)):
        raise RuntimeError('Cannot verify preview geometry')
    return {'capture_excluded': excluded, 'click_through': fullscreen,
            'x': actual.left, 'y': actual.top, 'width': actual.right-actual.left, 'height': actual.bottom-actual.top}
