"""Regression: unrelated button-up events must never follow a left click."""
import sys
from types import SimpleNamespace
import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Win32 backend')

@pytest.fixture
def native_input(monkeypatch):
    from win10_bridge_mcp import windows_native as n
    sent=[]
    n._HELD_BUTTONS.clear(); n._HELD_KEYS.clear()
    monkeypatch.setattr(n,'_send',lambda inp: sent.append((inp.type,inp.payload.mi.dwFlags if inp.type==0 else inp.payload.ki.dwFlags,inp.payload.mi.mouseData if inp.type==0 else inp.payload.ki.wVk)))
    monkeypatch.setattr(n,'_stop_if_needed',lambda: None)
    monkeypatch.setattr(n,'_activate',lambda _: None)
    monkeypatch.setattr(n,'_position',lambda *_: None)
    monkeypatch.setattr(n,'_verify_hit',lambda *_: None)
    yield n,sent
    n._HELD_BUTTONS.clear(); n._HELD_KEYS.clear()

@pytest.mark.parametrize('button',['left','right','middle','x1','x2'])
def test_click_sends_only_selected_button(native_input,button):
    n,sent=native_input
    n.apply_mouse(SimpleNamespace(rect=SimpleNamespace(absolute=lambda x,y:(x,y))),'click',button,1,1,1,1,100,2,1,'vertical',())
    down,up,data=n.BUTTON_FLAGS[button]
    assert sent==[(0,down,data),(0,up,data)]
    n.release_all()
    assert len(sent)==2

def test_scroll_never_sends_button_events(native_input):
    n,sent=native_input
    n.apply_mouse(SimpleNamespace(rect=SimpleNamespace(absolute=lambda x,y:(x,y))),'scroll','left',1,1,1,1,100,2,2,'vertical',())
    assert sent==[(0,n.MOUSE_WHEEL,240)]

def test_abort_releases_only_held_input(native_input,monkeypatch):
    n,sent=native_input
    n._mouse(n.MOUSE_LEFT_DOWN)
    n._virtual_key(0x11,True)
    n.release_all()
    assert sent==[(0,n.MOUSE_LEFT_DOWN,0),(1,0,0x11),(0,n.MOUSE_LEFT_UP,0),(1,2,0x11)]
    n.release_all()
    assert len(sent)==4
