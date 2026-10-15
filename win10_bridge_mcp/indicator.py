"""Visible, non-interactive desktop border for an authorized input session."""
from __future__ import annotations
import atexit
import queue
import threading
import time
from functools import lru_cache

_lock = threading.Lock()
_process = None
_closed = None
_target = None
_state_lock = threading.Lock()
_monitors = []


def status():
    with _state_lock:
        return {'active': active(), 'monitors': [dict(m) for m in _monitors] if active() else []}


def mark_target(hwnd, x, y):
    """Visual app cursor only; never moves or clicks the Windows pointer."""
    global _target
    _target = (hwnd, x, y, time.monotonic() + 2)


def active():
    return _process is not None and _process.is_alive() and not _closed.is_set()


def close():
    if _closed is not None:
        _closed.set()
    if _process is not None:
        _process.join(1)


def reset_for_new_session():
    global _process, _closed, _target
    with _lock:
        close()
        if _process is not None and _process.is_alive():
            raise RuntimeError('Previous indicator has not exited; session remains stopped')
        _process = None
        _closed = None
        _target = None


def ensure(session_stop):
    global _process, _closed
    with _lock:
        if session_stop.is_set():
            raise InterruptedError('Computer Use was cancelled')
        if _process is not None:
            if not active():
                session_stop.set()
                raise InterruptedError('Computer Use indicator closed; session stopped')
            return
        _closed = threading.Event()
        ready = threading.Event()
        errors = queue.Queue()
        _process = threading.Thread(target=_run, args=(_closed, ready, errors), daemon=True)
        _process.start()
        started = ready.wait(5)
        if not started or _closed.is_set() or not _process.is_alive():
            state = f'ready={started}, closed={_closed.is_set()}, alive={_process.is_alive()}'
            session_stop.set()
            close()
            detail = errors.get(timeout=1) if not errors.empty() else state
            raise RuntimeError('Computer Use indicator failed to start: ' + detail)
        process, closed = _process, _closed
        def watch():
            while not session_stop.wait(.02):
                if not process.is_alive():
                    session_stop.set()
                    break
            closed.set()
        threading.Thread(target=watch, daemon=True).start()


@lru_cache(maxsize=4)
def _logo(size):
    from PIL import Image
    from pathlib import Path
    with Image.open(Path(__file__).with_name('assets') / 'taskkit-logo.png') as logo:
        return logo.convert('RGBA').resize((size,size),Image.Resampling.LANCZOS)


def _render(width, height, origin_x=0, origin_y=0):
    from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageFilter
    import os
    image = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(image)
    for depth in range(18):
        alpha = round(210 * (1-depth/18)**1.8)
        draw.rectangle((depth, depth, width-1-depth, height-1-depth), outline=(42, 159, 255, alpha))
    left, right = width//2-210, width//2+210
    top, bottom = 24, 70
    # Small static layers provide depth without a GPU renderer or animation loop.
    shadow = Image.new('RGBA', (444,78))
    ImageDraw.Draw(shadow).rounded_rectangle((12,13,432,61),radius=14,fill=(1,12,28,170))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(5)),(left-12,top-8))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((left,top+4,right,bottom+4),radius=13,fill=(3,15,32,240),outline=(16,79,127,200),width=1)
    surface = Image.new('RGBA',(420,46))
    sd=ImageDraw.Draw(surface)
    for row in range(46):
        t=row/45
        sd.line((0,row,420,row),fill=(round(15-7*t),round(53-28*t),round(89-39*t),248))
    mask=Image.new('L',surface.size)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,419,45),radius=12,fill=255)
    surface.putalpha(ImageChops.multiply(surface.getchannel('A'),mask))
    image.alpha_composite(surface,(left,top))
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((left,top,right,bottom),radius=12,outline=(83,173,231,195),width=1)
    draw.line((left+17,top+1,right-17,top+1),fill=(169,224,255,200),width=1)
    image.alpha_composite(_logo(34),(left+10,top+6))
    draw.ellipse((right-19,top+20,right-13,top+26),fill=(68,218,255,255))
    font = ImageFont.truetype(os.path.join(os.environ.get('SystemRoot', 'C:/Windows'), 'Fonts', 'segoeuib.ttf'), 16)
    draw.text((width//2+9,top+24), 'TaskKit MCP in use - ESC to cancel.', font=font, fill=(232, 246, 255, 255), anchor='mm')
    target=_target
    if target and time.monotonic() < target[3]:
        from . import windows_native as n
        hwnd, sx, sy, _ = target
        hit=n.U.WindowFromPoint(n.POINT(sx,sy))
        x, y=sx-origin_x,sy-origin_y
        if hit and n.U.GetAncestor(hit,2)==hwnd and 0<=x<width-35 and 0<=y<height-35:
            draw.polygon(((x,y),(x+4,y+27),(x+11,y+19),(x+17,y+29),(x+22,y+26),(x+16,y+17),(x+28,y+16)),fill=(48,187,255,255),outline=(233,250,255,255),width=2)
    # UpdateLayeredWindow requires premultiplied RGB, not straight RGBA.
    r, g, b, alpha = image.split()
    return Image.merge('RGBA', (ImageChops.multiply(r, alpha), ImageChops.multiply(g, alpha), ImageChops.multiply(b, alpha), alpha))


def _run(closed, ready, errors):
    global _monitors
    windows = []
    try:
        import ctypes as ct
        from ctypes import wintypes as wt
        from . import windows_native as native, desktop
        u, g = native.U, native.G
        monitor_info = desktop.list_monitors()
        monitors = [(m['x'], m['y'], m['width'], m['height']) for m in monitor_info]
        u.CreateWindowExW.argtypes = (wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ct.c_int, ct.c_int, ct.c_int, ct.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, ct.c_void_p)
        u.CreateWindowExW.restype = wt.HWND
        u.DestroyWindow.argtypes = (wt.HWND,)
        u.SetWindowPos.argtypes = (wt.HWND, wt.HWND, ct.c_int, ct.c_int, ct.c_int, ct.c_int, wt.UINT)
        u.SetWindowPos.restype = wt.BOOL
        u.SetWindowDisplayAffinity.argtypes = (wt.HWND, wt.DWORD)
        u.SetWindowDisplayAffinity.restype = wt.BOOL
        class SIZE(ct.Structure):
            _fields_ = [('cx', ct.c_long), ('cy', ct.c_long)]
        class BLEND(ct.Structure):
            _fields_ = [('op', ct.c_ubyte), ('flags', ct.c_ubyte), ('alpha', ct.c_ubyte), ('format', ct.c_ubyte)]
        u.UpdateLayeredWindow.argtypes = (wt.HWND, wt.HDC, ct.POINTER(native.POINT), ct.POINTER(SIZE), wt.HDC, ct.POINTER(native.POINT), wt.DWORD, ct.POINTER(BLEND), wt.DWORD)
        def paint(hwnd, x, y, width, height):
            # Layered, transparent, no-activate, tool window; disabled means
            # WindowFromPoint and the native input hit guard skip this overlay.
            dc = g.CreateCompatibleDC(None)
            bitmap = previous = None
            try:
                info = native.BITMAPINFO()
                info.bmiHeader.biSize = ct.sizeof(native.BITMAPINFOHEADER)
                info.bmiHeader.biWidth = width
                info.bmiHeader.biHeight = -height
                info.bmiHeader.biPlanes = 1
                info.bmiHeader.biBitCount = 32
                bits = ct.c_void_p()
                bitmap = g.CreateDIBSection(dc, ct.byref(info), 0, ct.byref(bits), None, 0)
                if not bitmap:raise ct.WinError()
                previous = g.SelectObject(dc, bitmap)
                pixels = _render(width, height, x, y).tobytes('raw', 'BGRA')
                ct.memmove(bits, pixels, len(pixels))
                if not u.UpdateLayeredWindow(hwnd, None, ct.byref(native.POINT(x,y)), ct.byref(SIZE(width,height)), dc, ct.byref(native.POINT(0,0)), 0, ct.byref(BLEND(0,0,255,1)), 2):raise ct.WinError()
                if not u.SetWindowPos(hwnd, wt.HWND(-1), x, y, width, height, 0x0010 | 0x0040):raise ct.WinError()
            finally:
                if previous:g.SelectObject(dc, previous)
                if bitmap:g.DeleteObject(bitmap)
                g.DeleteDC(dc)
        for x, y, width, height in monitors:
            hwnd = u.CreateWindowExW(0x80000 | 0x20 | 0x08000000 | 0x80, 'STATIC', 'TaskKit MCP input indicator', 0x80000000 | 0x08000000, x, y, width, height, None, None, None, None)
            if not hwnd:raise ct.WinError()
            u.SetPropW.argtypes = (wt.HWND, wt.LPCWSTR, wt.HANDLE)
            u.SetPropW.restype = wt.BOOL
            u.SetPropW(hwnd, 'TaskKitMCP.InternalView', 1)
            windows.append(hwnd)
            paint(hwnd,x,y,width,height)
        with _state_lock:
            _monitors = []
            for m, hwnd in zip(monitor_info, windows):
                excluded = bool(u.SetWindowDisplayAffinity(hwnd, 0x11))
                _monitors.append(dict(m, hwnd=int(hwnd), capture_excluded=excluded,
                                      capture_excluded_error=0 if excluded else ct.get_last_error()))
        ready.set()
        painted_target=_target
        last_raise = 0
        message = wt.MSG()
        u.PeekMessageW.argtypes = (ct.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT)
        u.DispatchMessageW.argtypes = (ct.POINTER(wt.MSG),)
        u.DispatchMessageW.restype = ct.c_ssize_t
        while not closed.wait(.03):
            # A later fullscreen/topmost preview can cover an existing topmost
            # indicator. Keep every monitor's banner above it without focus.
            if time.monotonic() - last_raise >= .25:
                for hwnd in windows:
                    if not u.SetWindowPos(hwnd, wt.HWND(-1), 0, 0, 0, 0, 0x1 | 0x2 | 0x10 | 0x40):
                        raise ct.WinError()
                last_raise = time.monotonic()
            current=_target if _target and time.monotonic()<_target[3] else None
            if current!=painted_target:
                for hwnd, bounds in zip(windows,monitors):paint(hwnd,*bounds)
                painted_target=current
            while u.PeekMessageW(ct.byref(message), None, 0, 0, 1):
                u.TranslateMessage(ct.byref(message))
                u.DispatchMessageW(ct.byref(message))
    except Exception as exc:
        errors.put(str(exc))
        closed.set()
        ready.set()
    finally:
        for hwnd in windows:
            try:u.DestroyWindow(hwnd)
            except Exception:pass
        with _state_lock:
            _monitors = []
        closed.set()


atexit.register(close)
