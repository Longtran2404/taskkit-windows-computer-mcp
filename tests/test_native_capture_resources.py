"""Execute unchanged GDI capture bodies with fake Win32 calls, not DLL/ABI tests."""
import ast
from io import BytesIO
import importlib.util
from pathlib import Path
from types import SimpleNamespace as S
import pytest
from PIL import Image
from win10_bridge_mcp.policy import Rect


def renderer(mode, fault=None):
    source=Path(importlib.util.find_spec('win10_bridge_mcp.windows_native').origin).read_text()
    tree=ast.parse(source)
    name='_capture_screen_direct' if mode=='desktop' else '_capture_direct'
    nodes=[n for n in tree.body if isinstance(n,ast.ImportFrom) and n.module=='__future__'
           or isinstance(n,ast.FunctionDef) and n.name==name]
    trace=[]; blits=[]
    class Pointer:
        def __init__(self,value=None): self.value=value
    def bitmap(dc,info,usage,pointer,section,offset):
        if fault=='dib': return 0
        pointer.value=123; return 3
    def select(dc,obj):
        trace.append('select' if obj==3 else 'restore')
        if fault=='select': return 0
        if fault=='select_error': return -1
        return 4
    def flush(): trace.append('flush'); return fault!='flush'
    def read(pointer,length):
        assert trace[-1]=='flush' or 'flush' in trace
        trace.append('read'); return b'\xff\x00\x00\x00'*4
    def blit(*args): trace.append('draw'); blits.append(args); return fault!='draw'
    u=S(GetDC=lambda hwnd:0 if fault=='getdc' else 1,
        ReleaseDC=lambda hwnd,dc:trace.append('release_desktop'), PrintWindow=lambda *args:blit(*args))
    g=S(CreateCompatibleDC=lambda dc:0 if fault=='createdc' else 2,
        GetMapMode=lambda dc:2 if fault=='mapping' else 1, CreateDIBSection=bitmap,
        SelectObject=select,BitBlt=blit,GdiFlush=flush,
        DeleteObject=lambda obj:trace.append('delete_bitmap'),DeleteDC=lambda dc:trace.append('delete_dc'))
    namespace={'__package__':'win10_bridge_mcp','ct':S(sizeof=lambda cls:40,c_void_p=Pointer,
        byref=lambda obj:obj,string_at=read,memset=lambda *args:trace.append('zero')),
        'BITMAPINFO':lambda:S(bmiHeader=S()),'BITMAPINFOHEADER':object,
        'U':u,'G':g,'PILImage':Image,'BytesIO':BytesIO,'MAX_CAPTURE_PIXELS':12_000_000,
        '_require_physical_mapping':lambda:None,'check_window':lambda _:None}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'native-gdi-body','exec'),namespace)
    def perform():
        if mode=='desktop': return namespace[name](Rect(-2,0,0,2),lambda:None)
        return namespace[name](S(hwnd=1,rect=Rect(-2,0,0,2)))
    return perform,trace,blits


@pytest.mark.parametrize('fault,cleanup',[
    ('getdc',[]),('createdc',['release_desktop']),('mapping',['delete_dc','release_desktop']),
    ('dib',['delete_dc','release_desktop']),('select',['delete_bitmap','delete_dc','release_desktop']),
    ('select_error',['delete_bitmap','delete_dc','release_desktop']),
    ('draw',['delete_bitmap','delete_dc','release_desktop']),
    ('flush',['delete_bitmap','delete_dc','release_desktop'])])
def test_desktop_native_failure_branches_release_only_created_resources(fault,cleanup):
    perform,trace,_=renderer('desktop',fault)
    with pytest.raises((OSError,RuntimeError)): perform()
    assert [x for x in trace if x.startswith(('delete','release'))]==cleanup
    assert 'read' not in trace


def test_desktop_native_negative_source_mapping_and_flush():
    perform,trace,blits=renderer('desktop')
    png,method,uniform=perform()
    assert png.startswith(b'\x89PNG')
    assert blits[0][3:8]==(2,2,1,-2,0)
    assert trace.index('draw') < trace.index('flush') < trace.index('read')
    assert 'restore' in trace
    assert trace[-3:]==['delete_bitmap','delete_dc','release_desktop']


def test_printwindow_flush_before_dib_read_and_cleanup():
    perform,trace,_=renderer('window')
    png,method,blank=perform()
    assert png.startswith(b'\x89PNG')
    assert trace.index('draw') < max(i for i,x in enumerate(trace) if x=='flush') < trace.index('read')
    assert trace[-2:]==['delete_bitmap','delete_dc']


def test_printwindow_flush_failure_never_reads_pixels():
    perform,trace,_=renderer('window','flush')
    with pytest.raises(OSError): perform()
    assert 'read' not in trace
    assert trace[-2:]==['delete_bitmap','delete_dc']


def test_printwindow_select_error_never_reads_or_restores_invalid_handle():
    perform,trace,_=renderer('window','select_error')
    with pytest.raises(OSError): perform()
    assert 'read' not in trace
    assert 'restore' not in trace
    assert trace[-2:]==['delete_bitmap','delete_dc']
