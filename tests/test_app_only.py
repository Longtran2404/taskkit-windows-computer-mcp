"""App-only control flow with fake COM providers; no actual Windows semantics."""
import ast
from contextlib import contextmanager
from dataclasses import replace
import importlib.util
from pathlib import Path
from types import SimpleNamespace as S
import sys
import threading
import asyncio
import time
import pytest
from win10_bridge_mcp import server, ui_access, bounded_worker
from win10_bridge_mcp.policy import UnsupportedControlError


@pytest.fixture
def app(bridge, monkeypatch):
    native,cfg=bridge
    cfg.update(mouse_control_mode='disabled', semantic_control_mode='app_session')
    effects=[]
    pattern=S(CurrentIsReadOnly=False, CurrentValue='', CurrentIsSelected=False,
              CurrentHorizontallyScrollable=True, CurrentVerticallyScrollable=True,
              CurrentHorizontalScrollPercent=10., CurrentVerticalScrollPercent=20.)
    def set_value(value): effects.append(('value',value)); pattern.CurrentValue=value
    def select(): effects.append(('select',)); pattern.CurrentIsSelected=True
    def scroll(h,v):
        effects.append(('scroll',h,v))
        if h != 2: pattern.CurrentHorizontalScrollPercent+=1
        if v != 2: pattern.CurrentVerticalScrollPercent+=1
    pattern.SetValue=set_value; pattern.Select=select; pattern.Scroll=scroll
    pattern.Invoke=lambda: effects.append(('invoke',))
    raw=S(QueryInterface=lambda _: pattern)
    supported={1,2,3,4}
    c=S(CurrentAutomationId='item', CurrentIsPassword=False, CurrentIsEnabled=True,
        CurrentProcessId=native.current.pid, CurrentControlType=1, CurrentName='safe label',
        CurrentBoundingRectangle=S(left=-1180,top=-180,right=-800,bottom=100),
        GetCurrentPattern=lambda code: raw if code in supported else None)
    types=S(UIA_ValuePatternId=1,UIA_InvokePatternId=2,UIA_SelectionItemPatternId=3,UIA_ScrollPatternId=4,
            IUIAutomationValuePattern='v',IUIAutomationInvokePattern='i',
            IUIAutomationSelectionItemPattern='s',IUIAutomationScrollPattern='r')
    root=S(CurrentNativeWindowHandle=native.current.hwnd,CurrentProcessId=native.current.pid)
    c.parent=root
    automation=S(ElementFromHandle=lambda hwnd: root, CompareElements=lambda one,two: one is two,
                 RawViewWalker=S(GetParentElement=lambda node: getattr(node,'parent',None)))
    c.automation=automation
    c.root=root
    @contextmanager
    def elements(hwnd, *, with_root=False):
        assert hwnd==native.current.hwnd
        yield (types,[c],automation,root) if with_root else (types,[c])
    monkeypatch.setattr(ui_access,'elements',elements)
    def forbidden(*args,**kwargs): pytest.fail('app-only called physical input/focus API')
    for name in ['_activate','apply_mouse','apply_text','apply_keys','SetCursorPos','SendInput','SetForegroundWindow']:
        monkeypatch.setattr(native,name,forbidden,raising=False)
    tree=ast.parse(Path(importlib.util.find_spec('win10_bridge_mcp.windows_native').origin).read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.ImportFrom) and n.module=='__future__'
           or isinstance(n,ast.FunctionDef) and n.name=='_native_job']
    checks=[]
    def check(win,*,foreground=False):
        checks.append(foreground)
        assert foreground is False,'app-only required foreground'
        native.check_window(win)
    namespace={'__package__':'win10_bridge_mcp','check_window':check,'time':time}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'native-app-worker-body','exec'),namespace)
    native._native_job=namespace['_native_job']
    c.job_namespace=namespace
    from win10_bridge_mcp import config
    monkeypatch.setattr(config,'load_config',lambda:server.load_config())
    monkeypatch.setitem(sys.modules,'win10_bridge_mcp.windows_native',native)
    def run(target,payload,*,timeout,guard,on_unreaped):
        assert timeout==3
        assert payload[0].startswith('app_')
        guard()
        result=target(payload,threading.Event())
        guard()
        return result
    monkeypatch.setattr(bounded_worker,'run',run)
    return native,cfg,c,pattern,supported,effects,checks


@pytest.mark.parametrize('action',['set_value','invoke','select','scroll'])
def test_supported_app_only_never_uses_physical_or_focus(app,ticket,action):
    native,cfg,c,pattern,supported,effects,checks=app
    result=server.app_control_action(native.current.id,ticket,'item',action,'Tiếng Việt 😀',
                                     'none','small_increment',False)
    assert result['execution_mode']=='app_only'
    assert not result['bridge_physical_input_sent']
    assert not result['bridge_focus_requested']
    assert len(effects)==1
    assert checks and not any(checks)
    assert cfg['mouse_control_mode']=='disabled'
    assert not server.CONSENT.armed(cfg)
    assert ticket not in server.REGISTRY._tickets
    if action=='set_value': assert result['value_matches']
    if action=='select': assert result['selected']
    if action=='scroll': assert result['percent_changed']


@pytest.mark.parametrize('action,pattern_id',[('set_value',1),('invoke',2),('select',3),('scroll',4)])
def test_missing_pattern_clear_error_no_fallback(app,ticket,action,pattern_id):
    native,_,_,_,supported,effects,_=app
    supported.remove(pattern_id)
    result=asyncio.run(server.mcp.call_tool('app_control_action',{
        'window_id':native.current.id,'capture_id':ticket,'automation_id':'item',
        'action':action,'vertical':'small_increment','dry_run':False}))
    assert result.isError
    assert result.structuredContent['error']['code']=='unsupported_control'
    assert not effects


@pytest.mark.parametrize('fault',['password','pid','bounds','disabled','readonly','axis'])
def test_control_scope_password_and_capability_refusals(app,ticket,fault):
    native,_,c,p,_,effects,_=app
    action='set_value'
    if fault=='password': c.CurrentIsPassword=True
    if fault=='pid': c.CurrentProcessId+=1
    if fault=='bounds': c.CurrentBoundingRectangle.left=-9999
    if fault=='disabled': c.CurrentIsEnabled=False
    if fault=='readonly': p.CurrentIsReadOnly=True
    if fault=='axis': p.CurrentVerticallyScrollable=False; action='scroll'
    with pytest.raises((ValueError,PermissionError,UnsupportedControlError)):
        server.app_control_action(native.current.id,ticket,'item',action,'new','none','small_increment',False)
    assert not effects


@pytest.mark.parametrize('fault',['stop','identity','dpi','expired_token'])
def test_app_only_rechecks_after_consent(app,ticket,monkeypatch,fault):
    native,_,_,_,_,effects,_=app
    def consent(_):
        if fault=='stop': native.SESSION_STOP.set()
        if fault=='identity': native.current=replace(native.current,id='other')
        if fault=='dpi': native.current=replace(native.current,dpi=192)
        if fault=='expired_token': server.REGISTRY.ttl=0
        return True
    monkeypatch.setattr(server,'ask_local_consent',consent)
    with pytest.raises((ValueError,InterruptedError)):
        server.app_control_action(native.current.id,ticket,'item','invoke',dry_run=False)
    assert not effects


def test_app_only_disabled_dry_run_and_decline(app,ticket,monkeypatch):
    native,cfg,_,_,_,effects,_=app
    cfg['semantic_control_mode']='disabled'
    assert server.app_control_action(native.current.id,ticket,'item','invoke')['dry_run']
    with pytest.raises(PermissionError):
        server.app_control_action(native.current.id,ticket,'item','invoke',dry_run=False)
    cfg['semantic_control_mode']='app_confirm_each'
    monkeypatch.setattr(server,'ask_local_consent',lambda _:False)
    with pytest.raises(PermissionError):
        server.app_control_action(native.current.id,ticket,'item','invoke',dry_run=False)
    assert not effects
    assert ticket in server.REGISTRY._tickets


def test_app_session_window_scoped_expiring_consent(app,ticket,monkeypatch):
    native,cfg,_,_,_,_,_=app
    dialogs=[]
    monkeypatch.setattr(server,'ask_local_consent',lambda text: dialogs.append(text) or True)
    server.app_control_action(native.current.id,ticket,'item','invoke',dry_run=False)
    def new_ticket():
        w=native.current
        return server.REGISTRY.issue(w.id,w.rect,'fake',dpi=w.dpi).token
    server.app_control_action(native.current.id,new_ticket(),'item','select',dry_run=False)
    assert len(dialogs)==1
    server.APP_CONSENT.expires=0
    server.app_control_action(native.current.id,new_ticket(),'item','invoke',dry_run=False)
    assert len(dialogs)==2
    native.current=replace(native.current,id='new-window')
    server.app_control_action(native.current.id,new_ticket(),'item','invoke',dry_run=False)
    assert len(dialogs)==3
    assert all('up to 5 minutes' in d for d in dialogs)


def test_password_flag_change_before_pattern_call_blocks_effect(app,ticket):
    native,_,c,p,_,effects,_=app
    original=c.GetCurrentPattern
    def changing(code):
        result=original(code)
        c.CurrentIsPassword=True
        return result
    c.GetCurrentPattern=changing
    with pytest.raises(PermissionError):
        server.app_control_action(native.current.id,ticket,'item','set_value','never',dry_run=False)
    assert not effects


def test_inspection_advertises_patterns_without_password_reads(app):
    native,_,c,_,_,_,_=app
    result=ui_access._inspect(native.current.hwnd,lambda:None)
    assert set(result[0]['app_only_patterns'])=={'set_value','invoke','select','scroll'}
    c.CurrentIsPassword=True
    c.GetCurrentPattern=lambda _:pytest.fail('password pattern was read')
    assert ui_access._inspect(native.current.hwnd,lambda:None)==[]


@pytest.mark.parametrize('fault',['reparent','root_changed','root_pid','root_hwnd'])
def test_current_uia_root_and_ancestry_rechecked_before_effect(app,ticket,fault):
    native,_,c,_,_,effects,_=app
    original=c.GetCurrentPattern
    def change(code):
        result=original(code)
        if fault=='reparent': c.parent=S(CurrentNativeWindowHandle=999,CurrentProcessId=native.current.pid)
        if fault=='root_changed': c.automation.ElementFromHandle=lambda hwnd:S(CurrentNativeWindowHandle=hwnd)
        if fault=='root_pid': c.root.CurrentProcessId+=1
        if fault=='root_hwnd': c.root.CurrentNativeWindowHandle+=1
        return result
    c.GetCurrentPattern=change
    with pytest.raises(PermissionError):
        server.app_control_action(native.current.id,ticket,'item','invoke',dry_run=False)
    assert not effects


@pytest.mark.parametrize('action',['set_value','scroll'])
def test_app_per_operation_consent_shows_payload(app,ticket,monkeypatch,action):
    native,cfg,_,_,_,_,_=app
    cfg['semantic_control_mode']='app_confirm_each'
    summaries=[]
    monkeypatch.setattr(server,'ask_local_consent',lambda text:summaries.append(text) or True)
    server.app_control_action(native.current.id,ticket,'item',action,'Tiếng Việt\n😀',
                              'small_decrement','large_increment',False)
    if action=='set_value':
        assert 'Tiếng Việt\\n😀' in summaries[0]
        assert 'characters' in summaries[0]
    else:
        assert 'horizontal=small_decrement, vertical=large_increment' in summaries[0]


@pytest.mark.parametrize('fault',['stop','expiry','config','bounds','pid','disabled'])
def test_mutation_boundary_guards_after_resolving_pattern(app,ticket,monkeypatch,fault):
    native,cfg,c,_,_,effects,_=app
    original=c.GetCurrentPattern
    def change(code):
        result=original(code)
        if fault=='stop': native.SESSION_STOP.set()
        if fault=='expiry':
            deadline=server.APP_CONSENT.expires
            c.job_namespace['time']=S(monotonic=lambda:deadline+1)
        if fault=='config':
            changed=dict(cfg,semantic_control_mode='disabled')
            monkeypatch.setattr(server,'load_config',lambda:changed)
        if fault=='bounds': c.CurrentBoundingRectangle.right=9000
        if fault=='pid': c.CurrentProcessId+=1
        if fault=='disabled': c.CurrentIsEnabled=False
        return result
    c.GetCurrentPattern=change
    with pytest.raises((InterruptedError,PermissionError,UnsupportedControlError)):
        server.app_control_action(native.current.id,ticket,'item','invoke',dry_run=False)
    assert not effects


def test_stop_after_semantic_effect_reports_indeterminate(app,ticket):
    native,_,_,p,_,effects,_=app
    def invoke(): effects.append(('invoke',)); native.SESSION_STOP.set()
    p.Invoke=invoke
    result=asyncio.run(server.mcp.call_tool('app_control_action',{
        'window_id':native.current.id,'capture_id':ticket,'automation_id':'item','action':'invoke','dry_run':False}))
    assert result.isError
    assert result.structuredContent['error']['effects_verified'] is False
    assert effects==[('invoke',)]


def test_nul_value_rejected_before_consent_or_effect(app,ticket,monkeypatch):
    native,_,_,_,_,effects,_=app
    monkeypatch.setattr(server,'ask_local_consent',lambda _:pytest.fail('invalid value prompted'))
    with pytest.raises(ValueError):
        server.app_control_action(native.current.id,ticket,'item','set_value','prefix\x00suffix',dry_run=False)
    assert not effects


def test_worker_deadline_in_native_stop_guard_blocks_late_uia():
    from test_native_guards import guards
    import time
    n=guards(); n['U']=S(GetAsyncKeyState=lambda _:0); n['time']=time
    n['_worker_deadline']=time.monotonic()-1
    with pytest.raises(PermissionError,match='expired'): n['_stop_if_needed']()


def test_reparent_cycle_is_bounded_and_refused(app,ticket):
    native,_,c,_,_,effects,_=app
    c.parent=c
    with pytest.raises(PermissionError):
        server.app_control_action(native.current.id,ticket,'item','invoke',dry_run=False)
    assert not effects


def test_app_status_reports_only_active_grant(app,ticket):
    native,_,_,_,_,_,_=app
    server.app_control_action(native.current.id,ticket,'item','invoke',dry_run=False)
    status=server.bridge_status()
    assert status['mouse_mode']=='disabled'
    assert not status['session_armed']
    assert status['app_only']['session_armed']
    assert status['app_only']['session_window_id']==native.current.id
    server.APP_CONSENT.expires=0
    status=server.bridge_status()
    assert not status['app_only']['session_armed']
    assert status['app_only']['session_window_id'] is None
    assert status['app_only']['consent_remaining_seconds']==0


def test_inspection_omits_foreign_process_controls_before_name_reads(app):
    native,_,c,_,_,_,_=app
    c.CurrentProcessId+=1
    c.GetCurrentPattern=lambda _:pytest.fail('foreign process pattern queried')
    assert ui_access._inspect(native.current.hwnd,lambda:None,native.current.pid)==[]
