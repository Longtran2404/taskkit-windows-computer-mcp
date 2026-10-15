import json
import sys
from types import SimpleNamespace
import pytest
from win10_bridge_mcp import desktop, server, viewer
from win10_bridge_mcp.policy import Rect


def test_virtual_desktop_negative_origin_and_monitor_selection():
    monitors=[{'monitor_id':'left','x':-1920,'y':0,'width':1920,'height':1080},
              {'monitor_id':'main','x':0,'y':0,'width':2560,'height':1440}]
    assert desktop.monitor_bounds(monitors)==Rect(-1920,0,2560,1440)
    assert desktop.monitor_bounds(monitors,'left')==Rect(-1920,0,0,1080)
    with pytest.raises(ValueError): desktop.monitor_bounds(monitors,'missing')
    with pytest.raises(ValueError): desktop.monitor_bounds([dict(monitors[0],width=100000)])


def test_desktop_capture_refuses_selected_application_scope(monkeypatch):
    monkeypatch.setattr(server,'load_config',lambda:{'allowed':{'notepad.exe'}})
    with pytest.raises(PermissionError): server.capture_desktop()


def test_desktop_capture_is_read_only_and_no_window_ticket(monkeypatch):
    monkeypatch.setattr(server,'load_config',lambda:{'allowed':{'*'}})
    monkeypatch.setattr(server,'require_session',lambda _:pytest.fail('Read-only capture armed input'))
    monkeypatch.setattr(desktop,'capture',lambda *_:(b'png',{'origin_x':-1920,'origin_y':0}))
    result=server.capture_desktop()
    assert json.loads(result.content[0].text)=={'origin_x':-1920,'origin_y':0}
    assert result.content[1].type=='image'


def test_show_desktop_cannot_bypass_application_scope(monkeypatch):
    monkeypatch.setattr(server,'load_config',lambda:{'allowed':{'notepad.exe'},'mouse_control_mode':'disabled'})
    with pytest.raises(PermissionError): server.show_live_view(source='desktop')


@pytest.mark.skipif(sys.platform!='win32',reason='Native dialogs')
def test_disabled_parent_identifies_dialog_and_refuses_activation(monkeypatch):
    from win10_bridge_mcp import windows_native as n
    parent=SimpleNamespace(hwnd=100,id='1:64')
    dialog=SimpleNamespace(hwnd=200,id='1:c8')
    monkeypatch.setattr(n.U,'GetWindow',lambda hwnd,cmd:200 if cmd==6 and hwnd==100 else 100 if hwnd==200 else 0)
    monkeypatch.setattr(n.U,'IsWindowEnabled',lambda hwnd:hwnd!=100)
    def pid(_,value):
        n.ct.cast(value,n.ct.POINTER(n.wt.DWORD)).contents.value=1
    monkeypatch.setattr(n.U,'GetWindowThreadProcessId',pid)
    assert n.window_details(parent,[parent,dialog])['blocked_by_window_id']=='1:c8'
    assert n.window_details(dialog,[parent,dialog])['owner_window_id']=='1:64'
    with pytest.raises(RuntimeError,match='1:c8'): n.require_unblocked(parent)
    n.require_unblocked(dialog)


def test_preview_mode_change_does_not_clear_stop(monkeypatch):
    viewer.STOP.set()
    monkeypatch.setattr(server,'load_config',lambda:{'allowed':{'*'},'mouse_control_mode':'foreground_session'})
    monkeypatch.setattr(server,'require_session',lambda _:(_ for _ in ()).throw(InterruptedError('Stopped')))
    with pytest.raises(InterruptedError): server.show_live_view(source='desktop',fullscreen=True)
    assert viewer.STOP.is_set()
    viewer.STOP.clear()


@pytest.mark.skipif(sys.platform!='win32',reason='Native owned windows')
def test_small_untitled_owned_dialog_is_not_filtered_out(monkeypatch):
    from win10_bridge_mcp import windows_native as n
    monkeypatch.setattr(n.U,'IsWindowVisible',lambda _:True)
    monkeypatch.setattr(n.U,'IsIconic',lambda _:False)
    monkeypatch.setattr(n.U,'GetPropW',lambda *_:None)
    monkeypatch.setattr(n.U,'GetWindow',lambda *_:100)
    monkeypatch.setattr(n.U,'GetWindowThreadProcessId',lambda *_:1)
    monkeypatch.setattr(n,'executable',lambda _:'notepad.exe')
    def rect(_,value):
        r=n.ct.cast(value,n.ct.POINTER(n.RECT)).contents
        r.left,r.top,r.right,r.bottom=0,0,60,30
        return True
    monkeypatch.setattr(n.U,'GetWindowRect',rect)
    monkeypatch.setattr(n.U,'GetWindowTextLengthW',lambda _:0)
    monkeypatch.setattr(n.U,'GetWindowTextW',lambda *_:0)
    monkeypatch.setattr(n.U,'EnumWindows',lambda cb,_:cb(123,0))
    assert n.enumerate_windows(frozenset({'notepad.exe'}))[0].title=='[Untitled dialog]'
    monkeypatch.setattr(n.U,'GetWindow',lambda *_:0)
    assert n.enumerate_windows(frozenset({'notepad.exe'}))==[]
