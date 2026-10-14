"""Pure policy tests (no Windows input required)."""
import pytest
from win10_bridge_mcp.policy import (
    Rect, CaptureRegistry, drag_points, normalize_allowlist,
    parse_modifiers, validate_mouse
)


def test_rect_edges_and_negative_monitor_origin():
    r = Rect(-1800, 100, -1000, 900)
    assert r.absolute(0,0) == (-1800,100)
    assert r.absolute(799,799) == (-1001,899)
    with pytest.raises(ValueError): r.absolute(800,1)
    with pytest.raises(ValueError): r.absolute(-1,1)


def test_capture_ticket_expiry_replay_and_geometry():
    r = Rect(1,2,201,302)
    reg = CaptureRegistry(ttl=10)
    t = reg.issue('1:123', r, 'PrintWindow', now=10)
    assert reg.verify(t.token, '1:123', r, now=15) == t
    with pytest.raises(ValueError): reg.verify(t.token, '1:123', Rect(1,2,202,302), now=15)
    with pytest.raises(ValueError): reg.verify(t.token, '1:123', r, now=20)
    t = reg.issue('1:123', r, 'PrintWindow', now=30)
    reg.consume(t.token)
    with pytest.raises(ValueError): reg.verify(t.token, '1:123', r, now=31)


def test_allowlist_strict_names():
    assert normalize_allowlist(['notepad', 'Revit.exe']) == frozenset({'notepad.exe','revit.exe'})
    with pytest.raises(ValueError): normalize_allowlist(['../foo.exe'])
    with pytest.raises(ValueError): normalize_allowlist([])


def test_mouse_gestures_and_rejections():
    for action in ('move','click','double_click','drag','scroll','hold'):
        assert validate_mouse(action,'left',300,12,1,'vertical','ctrl+shift') == ('ctrl','shift')
    with pytest.raises(ValueError): validate_mouse('drag','x1',300,12,1,'vertical','')
    with pytest.raises(ValueError): validate_mouse('drag','left',7000,12,1,'vertical','')
    with pytest.raises(ValueError): validate_mouse('scroll','left',300,12,100,'vertical','')
    with pytest.raises(ValueError): parse_modifiers('alt+alt')
    assert drag_points((0,0),(100,50),10)[-1] == (100,50)
