from contextlib import contextmanager
from types import SimpleNamespace as S
import pytest
from win10_bridge_mcp import ui_access, server


@pytest.fixture
def controls(monkeypatch):
    effects=[]
    pattern=S(CurrentValue='Tiếng Việt 😀', SetValue=lambda text: effects.append(text), Invoke=lambda: effects.append('invoke'))
    raw=S(QueryInterface=lambda interface: pattern)
    edit=S(CurrentAutomationId='15', CurrentControlType=1, CurrentIsPassword=False,
           CurrentIsEnabled=True, GetCurrentPattern=lambda code: raw)
    button=S(CurrentAutomationId='1', CurrentControlType=2, CurrentIsPassword=False,
             CurrentIsEnabled=True, GetCurrentPattern=lambda code: raw)
    types=S(UIA_EditControlTypeId=1, UIA_ButtonControlTypeId=2,
            UIA_ValuePatternId=3, UIA_InvokePatternId=4,
            IUIAutomationValuePattern='value', IUIAutomationInvokePattern='invoke')
    @contextmanager
    def elements(hwnd): yield types, [edit, button]
    monkeypatch.setattr(ui_access, 'elements', elements)
    return edit, button, effects


@pytest.mark.parametrize('action', ['set_value', 'invoke'])
def test_guard_immediately_before_uia_effect(controls, action):
    effects=controls[2]
    def stopped(): raise InterruptedError('stop while resolving COM pattern')
    with pytest.raises(InterruptedError):
        ui_access._dispatch(action, 1, ('15', 'new') if action=='set_value' else ('1',), stopped)
    assert effects == []


def test_uia_password_disabled_duplicate_rejected(controls):
    edit, _, effects=controls
    edit.CurrentIsPassword=True
    with pytest.raises(ValueError): ui_access._value(1, '15', 'never', lambda: None)
    edit.CurrentIsPassword=False; edit.CurrentIsEnabled=False
    with pytest.raises(RuntimeError): ui_access._value(1, '15', 'never', lambda: None)
    assert effects == []


def test_uia_guard_after_mutation_reports_indeterminate(controls):
    calls=[]
    def guard():
        calls.append(1)
        if len(calls)>1: raise InterruptedError('stop after SetValue')
    with pytest.raises(InterruptedError): ui_access._value(1, '15', 'new', guard)
    assert controls[2] == ['new']


@pytest.mark.parametrize('action', ['set_value', 'invoke'])
def test_control_action_owner_armed_and_one_use(bridge, ticket, monkeypatch, action):
    native, cfg=bridge
    seen=[]
    def value(win, identifier, text=None, *, guard, deadline=None):
        guard(); assert deadline > 0; seen.append(action); return text
    def invoke(win, identifier, guard, *, deadline=None):
        guard(); assert deadline > 0; seen.append(action)
    monkeypatch.setattr(ui_access, 'value', value)
    monkeypatch.setattr(ui_access, 'invoke', invoke)
    result=server.control_action(native.current.id, ticket, '15', action, 'new', False)
    assert seen == [action]
    assert ticket not in server.REGISTRY._tickets
    assert server.CONSENT.armed(cfg)


def test_control_disabled_cannot_mutate(bridge, ticket, monkeypatch):
    native, cfg=bridge
    cfg['mouse_control_mode']='disabled'
    monkeypatch.setattr(ui_access, 'value', lambda *args, **kw: pytest.fail('mutation attempted'))
    with pytest.raises(PermissionError):
        server.control_action(native.current.id, ticket, '15', 'set_value', 'new', False)


def test_child_stop_relays_permanent_parent_latch(bridge, monkeypatch):
    import sys
    from win10_bridge_mcp import bounded_worker
    native, _=bridge
    native._native_job=lambda *_: None
    monkeypatch.setitem(sys.modules, 'win10_bridge_mcp.windows_native', native)
    def child_stop(*args, **kwargs): raise InterruptedError('Esc detected in child')
    monkeypatch.setattr(bounded_worker, 'run', child_stop)
    with pytest.raises(InterruptedError):
        ui_access._run('inspect', native.current, (), lambda: None)
    assert native.SESSION_STOP.is_set()


def test_duplicate_edit_and_password_button_refused(controls, monkeypatch):
    edit, button, effects=controls
    original=ui_access.elements
    @contextmanager
    def duplicate(hwnd):
        with original(hwnd) as (types, items): yield types, items+[edit]
    monkeypatch.setattr(ui_access,'elements',duplicate)
    with pytest.raises(ValueError): ui_access._value(1,'15','new',lambda:None)
    button.CurrentIsPassword=True
    with pytest.raises(ValueError): ui_access._invoke(1,'1',lambda:None)
    assert effects==[]
