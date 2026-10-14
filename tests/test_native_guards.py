"""Compile unchanged native guard bodies with fake Win32 functions on Linux.

This exercises control flow only, not Windows DLL calls or the ctypes ABI.
"""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace as S
import threading
import pytest
from win10_bridge_mcp import viewer


def guards():
    source=Path(importlib.util.find_spec('win10_bridge_mcp.windows_native').origin).read_text()
    tree=ast.parse(source)
    nodes=[n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module=='__future__'
           or isinstance(n, ast.FunctionDef) and n.name in {'latch_stop','_stop_if_needed','_verify_hit'}]
    class Point:
        def __init__(self): self.x=self.y=0
    namespace={'__package__': 'win10_bridge_mcp', 'SESSION_STOP': threading.Event(),
               '_worker_cancel': None, '_worker_deadline': None,
               '_stop_callbacks': [],
               'ct': S(byref=lambda point: point), 'POINT': Point}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'native-guard-bodies', 'exec'), namespace)
    return namespace


def test_native_hit_uses_actual_cursor_and_rejects_clamp():
    n=guards(); seen=[]; actual=[50,60]
    def cursor(point): point.x,point.y=actual; return True
    n['U']=S(GetCursorPos=cursor, WindowFromPoint=lambda point: seen.append((point.x,point.y)) or 1,
             GetAncestor=lambda hwnd, flag: 1)
    n['_verify_hit'](S(hwnd=1),50,60)
    assert seen==[(50,60)]
    actual[:]=[45,60]
    with pytest.raises(InterruptedError): n['_verify_hit'](S(hwnd=1),50,60)
    assert seen==[(50,60)]


@pytest.mark.parametrize('key', [0x1B,0x7B])
def test_native_stop_closes_shared_preview_and_persists(key):
    n=guards()
    n['U']=S(GetAsyncKeyState=lambda vk: 1 if vk==key else 0)
    with pytest.raises(InterruptedError): n['_stop_if_needed']()
    assert n['SESSION_STOP'].is_set()
    assert viewer._closed.is_set()
    n['U'].GetAsyncKeyState=lambda _: 0
    with pytest.raises(InterruptedError): n['_stop_if_needed']()


@pytest.mark.parametrize('flush_ok',[True,False])
def test_native_desktop_flush_precedes_read_and_resources_cleaned(flush_ok):
    from io import BytesIO
    from PIL import Image
    from win10_bridge_mcp.policy import Rect
    source=Path(importlib.util.find_spec('win10_bridge_mcp.windows_native').origin).read_text()
    tree=ast.parse(source)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_capture_screen_direct']
    trace=[]
    class Pointer:
        def __init__(self,value=None): self.value=value
    def bitmap(dc,info,usage,pointer,section,offset): pointer.value=123; return 3
    def flush(): trace.append('flush'); return flush_ok
    def read(pointer,length):
        assert 'flush' in trace,'DIB memory read before GDI flush'
        trace.append('read')
        return b'\xff\x00\x00\x00'*4
    u=S(GetDC=lambda hwnd:1,ReleaseDC=lambda hwnd,dc:trace.append('release_desktop'))
    g=S(CreateCompatibleDC=lambda dc:2,GetMapMode=lambda dc:1,CreateDIBSection=bitmap,
        SelectObject=lambda dc,bitmap:4,BitBlt=lambda *args:trace.append('blit') or True,
        GdiFlush=flush,DeleteObject=lambda bitmap:trace.append('delete_bitmap'),
        DeleteDC=lambda dc:trace.append('delete_dc'))
    namespace={'__package__':'win10_bridge_mcp','ct':S(sizeof=lambda cls:40,c_void_p=Pointer,
                byref=lambda obj:obj,string_at=read), 'BITMAPINFO':lambda:S(bmiHeader=S()),
                'BITMAPINFOHEADER':object,'U':u,'G':g,'PILImage':Image,'BytesIO':BytesIO,
                '_require_physical_mapping':lambda:None}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'native-desktop-body','exec'),namespace)
    if flush_ok:
        png,method,blank=namespace['_capture_screen_direct'](Rect(-2,0,0,2),lambda:None)
        assert png.startswith(b'\x89PNG') and method=='GDI desktop BitBlt'
        assert trace.index('flush') < trace.index('read')
    else:
        with pytest.raises(OSError,match='GdiFlush'):
            namespace['_capture_screen_direct'](Rect(-2,0,0,2),lambda:None)
        assert 'read' not in trace
    assert trace[-3:]==['delete_bitmap','delete_dc','release_desktop']
