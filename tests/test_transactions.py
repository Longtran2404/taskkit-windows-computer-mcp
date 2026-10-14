from dataclasses import replace
from types import SimpleNamespace
import pytest
from fakes import FakeAdapter
from win10_bridge_mcp import input_transaction as tx
from win10_bridge_mcp.policy import Rect


@pytest.fixture
def adapter(monkeypatch):
    a = FakeAdapter()
    monkeypatch.setattr(tx, 'time', SimpleNamespace(monotonic=lambda: a.clock))
    return a


def perform(a, action='click', button='left', modifiers=()):
    tx.mouse(a, a.current, action, button, 50, 50, 150, 150, 100, 5, 2, 'vertical', modifiers)


@pytest.mark.parametrize('button', ['left', 'right', 'middle', 'x1', 'x2'])
def test_click_buttons_owned_cleanup(adapter, button):
    perform(adapter, button=button)
    assert adapter.events == [('button', button, True), ('button', button, False)]
    assert not adapter.depressed


@pytest.mark.parametrize('action', ['move', 'click', 'double_click', 'drag', 'hold', 'scroll'])
def test_mouse_primitives_modifiers(adapter, action):
    perform(adapter, action, modifiers=('ctrl', 'shift', 'alt', 'space'))
    assert not adapter.depressed
    assert adapter.pointer == ((-1050, -50) if action == 'drag' else (-1150, -150))


@pytest.mark.parametrize('axis,amount', [('vertical', -240), ('horizontal', 360)])
def test_both_wheel_axes(adapter, axis, amount):
    tx.mouse(adapter, adapter.current, 'scroll', 'left', 20, 20, 20, 20, 100, 2, amount//120, axis, ('ctrl',))
    assert ('wheel', axis, amount) in adapter.events


def test_clamped_cursor_aborts_before_any_down(adapter):
    adapter.clamp = True
    with pytest.raises(InterruptedError, match='clamped'):
        perform(adapter, modifiers=('ctrl',))
    assert adapter.events == []


@pytest.mark.parametrize('fault,stage', [(fault, stage)
    for stage in ['position', 'hit', 'down', 'wait']
    for fault in ['focus', 'overlay', 'stop', 'resize', 'dpi', 'identity', 'cursor', 'user_key']
    if (fault, stage) != ('cursor', 'position')])
def test_faults_during_mouse_release_only_owned(adapter, fault, stage):
    def inject(name, a):
        if name != stage:
            return
        a.hook = lambda *_: None
        if fault == 'focus': a.foreground = 999
        if fault == 'overlay': a.overlay = True
        if fault == 'stop': a.stopped = True
        if fault == 'resize': a.current = replace(a.current, rect=Rect(0, 0, 600, 400))
        if fault == 'dpi': a.current = replace(a.current, dpi=192)
        if fault == 'identity': a.current = replace(a.current, id='reused:hwnd:pid')
        if fault == 'cursor': a.pointer = (9000, 9000)
        if fault == 'user_key': a.user_held.add(83)
    adapter.hook = inject
    # position overwrites a cursor change just before SetCursorPos; Windows cannot
    # detect that tiny race. Inject cursor at hit/down/wait for observable takeover.
    with pytest.raises((InterruptedError, RuntimeError)):
        perform(adapter, 'double_click', modifiers=('ctrl',))
    assert not adapter.depressed
    assert adapter.user_held in (set(), {83})
    downs = [(k, v) for k, v, d in adapter.events if d is True]
    ups = [(k, v) for k, v, d in adapter.events if d is False]
    assert sorted(downs) == sorted(ups)
    assert ('key', 83, False) not in adapter.events


@pytest.mark.parametrize('kind', ['mouse', 'keys', 'text'])
def test_stop_at_every_guard_boundary(adapter, kind):
    def operation():
        if kind == 'mouse': perform(adapter, 'drag', modifiers=('ctrl',))
        elif kind == 'keys': tx.keys(adapter, adapter.current, ('ctrl', 's'))
        else: tx.text(adapter, adapter.current, 'Việt 😀', True)
    operation()
    total = adapter.check_count
    for stage in range(1, total + 1):
        adapter.events.clear(); adapter.check_count = 0; adapter.clock = 0
        adapter.pointer = (-1000, 0); adapter.stopped = False
        def stop_here(name, a):
            if name == 'check' and a.check_count == stage:
                a.stopped = True
        adapter.hook = stop_here
        with pytest.raises(InterruptedError):
            operation()
        assert not adapter.depressed


@pytest.mark.parametrize('stage', ['activate', 'down', 'up', 'wait'])
def test_ctrl_a_focus_steal_aborts_following_text(adapter, stage):
    def hook(name, a):
        if name == stage:
            a.foreground = 999
    adapter.hook = hook
    with pytest.raises(RuntimeError):
        tx.text(adapter, adapter.current, 'never', True)
    assert not adapter.depressed
    assert not any(k == 'unicode' for k, _, _ in adapter.events)


def test_user_held_inputs_never_released(adapter):
    adapter.user_held = {1, 162, 83}
    with pytest.raises(InterruptedError):
        perform(adapter)
    assert adapter.events == []
    assert adapter.user_held == {1, 162, 83}


def test_unicode_vietnamese_emoji_and_owned_release(adapter):
    tx.text(adapter, adapter.current, 'ệ😀')
    units = [v for k, v, d in adapter.events if d]
    assert units == [ord('ệ'), 0xD83D, 0xDE00]
    assert not adapter.depressed


def test_cleanup_reports_release_failure(adapter):
    original = adapter.emit
    def fail_release(kind, value, down):
        if not down: raise OSError('UIPI')
        original(kind, value, down)
    adapter.emit = fail_release
    with pytest.raises(RuntimeError, match='release failed'):
        tx.keys(adapter, adapter.current, ('s',))


def test_delayed_key_up_state_settles_before_next_effect(adapter):
    original=adapter.emit
    held=adapter.held_inputs
    pending={}
    def emit(kind, value, down):
        original(kind, value, down)
        if not down:
            for code in adapter.code(kind, value): pending[code]=adapter.clock+.03
    def states():
        return held() | {code for code, until in pending.items() if adapter.clock < until}
    adapter.emit=emit; adapter.held_inputs=states
    tx.text(adapter, adapter.current, 'ab', True)
    assert [v for k,v,d in adapter.events if k=='unicode' and d] == [97,98]
    assert not adapter.depressed


def test_unsettled_up_fails_without_releasing_twice(adapter):
    original=adapter.emit
    held=adapter.held_inputs
    def emit(kind, value, down):
        original(kind,value,down)
        if not down: adapter.user_held.add(value)
    adapter.emit=emit
    with pytest.raises(InterruptedError, match='did not settle'):
        tx.keys(adapter, adapter.current, ('s',))
    assert adapter.events == [('key',83,True), ('key',83,False)]
    assert adapter.user_held == {83}
