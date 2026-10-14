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
