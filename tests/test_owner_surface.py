"""Authorization surface policy with synthetic HWND/Win32 objects."""
from types import SimpleNamespace as S
import ctypes as ct
import pytest
from win10_bridge_mcp import owner_surface


@pytest.mark.parametrize('hwnd,marked,protected',[(10,{10},True),(20,{10},True),(30,{10},True),(40,{10},False)])
def test_owner_root_and_owned_dialogs_protected(hwnd,marked,protected):
    api=S(root=lambda h:{20:10}.get(h,h),owner=lambda h:{30:10}.get(h,0),marked=lambda h:h in marked)
    assert owner_surface.protected_target(api,hwnd) is protected


def test_owner_chain_cycle_fails_closed():
    api=S(root=lambda h:h,owner=lambda h:h,marked=lambda h:False)
    with pytest.raises(PermissionError):owner_surface.protected_target(api,10)


@pytest.mark.parametrize('result,allowed',[(0,True),(0x102,False),(0x80,False),(0xFFFFFFFF,False)])
def test_desktop_barrier_excludes_active_or_abandoned_owner_surface(monkeypatch,result,allowed):
    calls=[]
    def fn(callback):
        # Mutable function wrapper emulates ctypes prototype attributes.
        def wrapped(*args):return callback(*args)
        return wrapped
    kernel=S(CreateMutexW=fn(lambda *_:123),WaitForSingleObject=fn(lambda *_:result),
             ReleaseMutex=fn(lambda _:calls.append('release')),CloseHandle=fn(lambda _:calls.append('close')))
    monkeypatch.setattr(owner_surface.sys,'platform','win32')
    monkeypatch.setattr(ct,'WinDLL',lambda *a,**k:kernel,raising=False)
    if allowed:
        with owner_surface.desktop_surface_barrier():calls.append('pixels')
        assert calls==['pixels','release','close']
    else:
        with pytest.raises(PermissionError):
            with owner_surface.desktop_surface_barrier():calls.append('pixels')
        assert 'pixels' not in calls and calls[-1]=='close'
        assert ('release' in calls) is (result==0x80)


def test_native_window_reader_checks_protection_before_metadata(monkeypatch):
    import ast,importlib.util
    from pathlib import Path
    source=Path(importlib.util.find_spec('win10_bridge_mcp.windows_native').origin).read_text()
    nodes=[n for n in ast.parse(source).body if isinstance(n,ast.ImportFrom) and n.module=='__future__'
           or isinstance(n,ast.FunctionDef) and n.name=='_read_window']
    api=S(root=lambda h:h,owner=lambda h:0,marked=lambda h:True)
    monkeypatch.setattr(owner_surface,'SurfaceAPI',lambda:api)
    namespace={'__package__':'win10_bridge_mcp',
               '_require_physical_mapping':lambda:pytest.fail('protected window metadata was read')}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'native-owner-protected-reader','exec'),namespace)
    with pytest.raises(PermissionError,match='protected'):
        namespace['_read_window'](10,frozenset({'python.exe'}))


def test_legacy_messagebox_uses_protected_owner(monkeypatch):
    from contextlib import contextmanager
    from win10_bridge_mcp import server
    calls=[]
    @contextmanager
    def owner():
        calls.append('protected owner entered')
        yield 42
        calls.append('protected owner left')
    def box(hwnd,*args):
        assert hwnd==42 and calls==['protected owner entered']
        calls.append('local MessageBox')
        return 6
    box.argtypes=None; box.restype=None
    monkeypatch.setattr(owner_surface,'protected_consent_window',owner)
    monkeypatch.setattr(ct,'WinDLL',lambda *a,**k:S(MessageBoxW=box),raising=False)
    assert server._consent_job('synthetic consent',None)
    assert calls==['protected owner entered','local MessageBox','protected owner left']
