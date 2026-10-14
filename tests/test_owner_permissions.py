"""Synthetic profiles and adapters only; no Windows owner grant or credential created."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as S
import threading
import time

import pytest
from mcp.types import InitializeRequestParams, Implementation, ClientCapabilities
from win10_bridge_mcp import server
from win10_bridge_mcp.permissions import PermissionRuntime, key_digest, validate_record, REQUEST_LEASE
from win10_bridge_mcp.permission_store import WindowsGrantStore, make_record
from win10_bridge_mcp.desktop_health import classify_context

# Deliberately fixed/public fixture. Never use this string as a real credential.
FIXTURE_SECRET = 'tkcu_v1_' + 'A' * 43


class FakeProtection:
    """Reversible fake codec; does not exercise DPAPI or Windows ACLs."""
    def secure(self, path): pass
    def crypt(self, data, *, decrypt=False):
        if decrypt:
            if not data.startswith(b'FAKE:'): raise PermissionError('bad fake blob')
            return data[5:][::-1]
        return b'FAKE:' + data[::-1]


def client():
    return S(client_params=InitializeRequestParams(protocolVersion='2025-11-25',
             clientInfo=Implementation(name='synthetic host', version='1'), capabilities=ClientCapabilities()))


@pytest.fixture
def owner(bridge, tmp_path, monkeypatch):
    native, cfg = bridge
    cfg.update(authorization_mode='persistent', semantic_control_mode='app_session')
    store = WindowsGrantStore(root=tmp_path/'owner'/'grants', protection=FakeProtection(), create=True)
    record = make_record(['notepad.exe'], ['read_targets','uia_read','capture_window','app_actions',
                         'physical_input','file_save','read_drives','local_preview'], FIXTURE_SECRET, 7)
    store.create(record)
    runtime = PermissionRuntime(lambda: store)
    env = {'TASKKIT_CLIENT_ID': record['profile_id'], 'TASKKIT_CLIENT_SECRET': FIXTURE_SECRET}
    runtime.configure(cfg, env)
    assert 'TASKKIT_CLIENT_SECRET' not in env
    runtime.start(cfg)
    session = client()
    monkeypatch.setattr(server, 'PERMISSIONS', runtime)
    monkeypatch.setattr(server.mcp, 'get_context', lambda: S(session=session))
    monkeypatch.setattr(server, 'desktop_health', lambda: {'usable_interactive_context':True})
    monkeypatch.setattr(server, 'ask_local_consent', lambda _: pytest.fail('persistent grant prompted again'))
    return runtime, store, session, record, cfg, native


def test_scope_reused_in_multiple_windows_without_prompt(owner, monkeypatch):
    runtime, store, session, record, cfg, native = owner
    with runtime.request(session):
        first = server.capture_window(native.current.id).structuredContent
        native.current = type(native.current)(id='new-window')
        second = server.capture_window(native.current.id).structuredContent
    assert first['capture_id'] != second['capture_id']
    assert runtime.status()['apps'] == ['notepad.exe']
    assert not server.CONSENT.armed(cfg)
    assert not server.APP_CONSENT.armed(cfg)


@pytest.mark.parametrize('capability', ['physical_input','file_save','app_actions','capture_monitor','capture_desktop'])
def test_capabilities_cannot_be_borrowed_from_capture(owner, capability):
    runtime, store, session, _, cfg, _ = owner
    runtime.end()
    record = store.read(runtime.profile_id)
    record['capabilities'] = ['capture_window']
    with store.locked(): store._write(record)
    runtime.start(cfg)
    with runtime.request(session):
        runtime.check(cfg,'capture_window','notepad.exe')
        with pytest.raises(PermissionError): runtime.check(cfg,capability)
        with pytest.raises(PermissionError): runtime.check(cfg,'capture_window','explorer.exe')


@pytest.mark.parametrize('mutation', ['new_session','identical_init','label_change','same_object_label_change'])
def test_identity_epoch_changes_cancel_connection(owner, mutation):
    runtime, _, session, _, cfg, _ = owner
    with runtime.request(session): runtime.check(cfg,'capture_window')
    if mutation == 'new_session': session = client()
    elif mutation == 'identical_init': session.client_params = session.client_params.model_copy(deep=True)
    elif mutation == 'label_change':
        session.client_params = session.client_params.model_copy(deep=True)
        session.client_params.clientInfo.name = 'different label'
    else: session.client_params.clientInfo.version = '2'
    with runtime.request(session):
        with pytest.raises(PermissionError): runtime.check(cfg,'capture_window')
    assert runtime.lease.cancelled.is_set()


@pytest.mark.parametrize('state', ['paused','revoked'])
def test_owner_state_change_invalidates_and_reconnect_cannot_rearm(owner, state):
    runtime, store, session, record, cfg, _ = owner
    with runtime.request(session): runtime.check(cfg)
    store.set_state(record['profile_id'],state)
    with runtime.request(session):
        with pytest.raises(PermissionError): runtime.check(cfg)
    runtime.end(); runtime.start(cfg)
    assert runtime.lease is None
    assert not runtime.status()['authenticated']


def test_orderly_reconnect_authenticates_and_gets_fresh_lease(owner):
    runtime, store, session, record, cfg, _ = owner
    with runtime.request(session): old = runtime.check(cfg)
    runtime.end()
    assert old.cancelled.is_set()
    assert store.read(record['profile_id'])['state'] == 'active'
    runtime.start(cfg)
    with runtime.request(client()):
        new = runtime.check(cfg)
        assert new is not old and new.record['lease_id'] != old.record['lease_id']
        with pytest.raises(PermissionError): runtime.check(cfg,lease=old)


@pytest.mark.parametrize('secret', [None, '', 'tkcu_v1_'+'B'*43, FIXTURE_SECRET+'x'])
def test_wrong_credential_does_not_claim_grant(owner, secret):
    runtime, store, _, record, cfg, _ = owner
    runtime.end()
    other = PermissionRuntime(lambda: store)
    env = {'TASKKIT_CLIENT_ID':record['profile_id'],'TASKKIT_CLIENT_SECRET':secret}
    other.configure(cfg,env); other.start(cfg)
    assert 'TASKKIT_CLIENT_SECRET' not in env
    assert other.lease is None
    assert store.read(record['profile_id'])['state'] == 'active'


def test_running_marker_blocks_crash_and_failed_stop_write_reconnect(owner, monkeypatch):
    runtime, store, _, record, cfg, _ = owner
    other = PermissionRuntime(lambda:store)
    other.configure(cfg, {'TASKKIT_CLIENT_ID':record['profile_id'],'TASKKIT_CLIENT_SECRET':FIXTURE_SECRET})
    other.start(cfg)
    assert other.lease is None
    monkeypatch.setattr(store,'set_state',lambda *_: (_ for _ in ()).throw(OSError('fake disk failure')))
    server.stop_permissions()
    assert runtime.stopping and runtime.lease.cancelled.is_set()
    runtime.end()
    assert store.read(record['profile_id'])['state']=='running'
    other.start(cfg)
    assert other.lease is None


@pytest.mark.parametrize('field,value', [('authorization_mode','legacy'),('allowed',frozenset({'notepad.exe','explorer.exe'})),
                                       ('capture_modes',['window','monitor']),('mouse_control_mode','disabled')])
def test_config_change_aborts_without_scope_expansion(owner, field, value):
    runtime, _, session, _, cfg, _ = owner
    with runtime.request(session):
        runtime.check(cfg)
        cfg[field]=value
        with pytest.raises(PermissionError): runtime.check(cfg)


def test_monotonic_deadline_blocks_clock_rollback(owner, monkeypatch):
    runtime, _, session, _, cfg, _ = owner
    runtime.lease.expires = time.monotonic()-1
    with runtime.request(session):
        with pytest.raises(PermissionError): runtime.check(cfg)


def test_pause_tool_reduces_access_returns_receipt_and_never_resumes(owner):
    runtime, store, _, record, _, _ = owner
    result=asyncio.run(server.mcp.call_tool('pause_access',{}))
    assert not result.isError and result.structuredContent['paused']
    assert store.read(record['profile_id'])['state']=='paused'
    assert runtime.lease.cancelled.is_set()
    names=asyncio.run(server.mcp.list_tools())
    assert not any(t.name in {'grant_access','resume_access','arm_session'} for t in names)


def test_async_cancellation_revokes_before_abandoned_capture_finishes(owner, monkeypatch):
    runtime, _, _, _, _, native = owner
    started=threading.Event(); released=threading.Event(); finished=threading.Event()
    original=native.capture_window
    def waiting(win, **kwargs):
        started.set()
        try:
            assert released.wait(2)
            kwargs['guard']()
            return original(win,**kwargs)
        finally: finished.set()
    monkeypatch.setattr(native,'capture_window',waiting)
    async def case():
        call=asyncio.create_task(server.mcp.call_tool('capture_window',{'window_id':native.current.id}))
        assert await asyncio.to_thread(started.wait,2)
        call.cancel()
        with pytest.raises(asyncio.CancelledError): await call
        assert runtime.lease.cancelled.is_set()
        released.set()
        assert await asyncio.to_thread(finished.wait,2)
    asyncio.run(case())
    assert not server.REGISTRY._tickets


def test_pause_during_capture_discards_result_and_token(owner, monkeypatch):
    _, store, session, record, _, native = owner
    native.capture_hook=lambda:store.set_state(record['profile_id'],'paused')
    result=asyncio.run(server.mcp.call_tool('capture_window',{'window_id':native.current.id}))
    assert result.isError and result.structuredContent['error']['code']=='permission_denied'
    assert all(x.type=='text' for x in result.content)
    assert not server.REGISTRY._tickets


def test_no_desktop_access_when_same_session_different_desktop(owner, monkeypatch):
    runtime, _, session, _, _, native = owner
    health=classify_context({'process_session_id':1,'console_session_id':1,'window_station':'WinSta0',
                            'thread_desktop':'SyntheticSandboxDesktop','input_desktop':'Default','foreground_hwnd':0})
    assert health['status']=='desktop_mismatch'
    monkeypatch.setattr(server,'desktop_health',lambda:health)
    result=asyncio.run(server.mcp.call_tool('capture_window',{'window_id':native.current.id}))
    assert result.isError and 'owner input desktop' in result.structuredContent['error']['message']
    assert not server.REGISTRY._tickets


@pytest.mark.parametrize('snapshot,ready', [
    ({'process_session_id':1,'window_station':'WinSta0','thread_desktop':'Default','input_desktop':'Default','foreground_hwnd':123},True),
    ({'process_session_id':0,'window_station':'WinSta0','thread_desktop':'Default','input_desktop':'Default','foreground_hwnd':123},False),
    ({'process_session_id':1,'window_station':'Service-0','thread_desktop':'Default','input_desktop':'Default','foreground_hwnd':123},False),
    ({'process_session_id':1,'window_station':'WinSta0','thread_desktop':'Default','input_desktop':None,'foreground_hwnd':123},False),
    ({'process_session_id':1,'window_station':'WinSta0','thread_desktop':'Default','input_desktop':'Default','foreground_hwnd':0},False)])
def test_context_health_is_metadata_not_live_verification(snapshot,ready):
    health=classify_context(snapshot)
    assert health['usable_interactive_context'] is ready
    assert health['live_operations_verified'] is False
    assert health['automatically_switches_desktop'] is False


def test_owner_enrollment_cannot_be_unattended_or_widen_eligibility(owner, monkeypatch):
    from win10_bridge_mcp.owner_permissions import enroll
    import secrets
    runtime, store, _, _, cfg, _=owner
    called=[]
    monkeypatch.setattr(secrets,'token_urlsafe',lambda _:called.append(1) or 'A'*43)
    for apps,caps,confirmed in [(['notepad.exe'],['capture_window'],False),
                                 (['explorer.exe'],['capture_window'],True),
                                 (['notepad.exe'],['capture_desktop'],True),([],['capture_window'],True)]:
        with pytest.raises(PermissionError): enroll(store,cfg,apps,caps,7,owner_confirmed=confirmed)
    assert not called
    profile,secret=enroll(store,cfg,['notepad.exe'],['capture_window'],7,owner_confirmed=True)
    assert called and store.read(profile)['key_digest']==key_digest(secret)
    assert secret.encode() not in store.path(profile).read_bytes()


@pytest.mark.parametrize('field,value', [('audience','other-server'),('apps',[]),('capabilities',[]),
    ('capabilities',['all_apps']),('expires_at',0),('issued_at',time.time()+999999),('state','auto_allow')])
def test_invalid_grant_fails_closed(owner,field,value):
    record=dict(owner[3], **{field:value})
    with pytest.raises((PermissionError,ValueError,TypeError)): validate_record(record)


def test_revoked_profile_irreversible_and_symlink_record_denied(owner,tmp_path):
    _,store,_,record,_,_=owner
    store.set_state(record['profile_id'],'revoked')
    with pytest.raises(PermissionError):store.set_state(record['profile_id'],'active')
    real=store.path(record['profile_id'])
    moved=real.with_suffix('.original'); real.rename(moved)
    try:real.symlink_to(moved)
    except OSError:pytest.skip('Host does not allow test symlinks')
    with pytest.raises(PermissionError):store.read(record['profile_id'])


def test_linux_has_no_plaintext_production_store_fallback(tmp_path):
    import sys
    if sys.platform=='win32':pytest.skip('Linux production refusal only')
    with pytest.raises(OSError):WindowsGrantStore(root=tmp_path/'permissions',create=True)


def test_real_sdk_eof_revokes_pending_handler_before_late_image(owner, monkeypatch):
    import anyio
    from mcp import ClientSession
    from mcp.shared.memory import create_client_server_memory_streams
    runtime, store, _, record, cfg, native=owner
    runtime.end()
    monkeypatch.setattr(server.mcp,'get_context',type(server.mcp).get_context.__get__(server.mcp))
    started=threading.Event(); released=threading.Event(); finished=threading.Event()
    original=native.capture_window
    def pending(win,**kwargs):
        started.set()
        try:
            assert released.wait(3)
            kwargs['guard']()
            return original(win,**kwargs)
        finally:finished.set()
    monkeypatch.setattr(native,'capture_window',pending)
    async def case():
        with anyio.fail_after(5):
            async with create_client_server_memory_streams() as (client_streams,server_streams):
                async with anyio.create_task_group() as tasks:
                    tasks.start_soon(server.mcp._mcp_server.run,*server_streams,
                                     server.mcp._mcp_server.create_initialization_options())
                    async with ClientSession(*client_streams) as connected:
                        await connected.initialize()
                        async def call():
                            try:await connected.call_tool('capture_window',{'window_id':native.current.id})
                            except Exception:pass  # Expected connection-closed response.
                        tasks.start_soon(call)
                        assert await anyio.to_thread.run_sync(lambda:started.wait(2))
                        old=runtime.lease
                        await client_streams[1].aclose()  # Real transport EOF, not an explicit test cancel.
                        for _ in range(100):
                            if old.cancelled.is_set():break
                            await anyio.sleep(.01)
                        assert old.cancelled.is_set()
                        released.set()
                        assert await anyio.to_thread.run_sync(lambda:finished.wait(2))
                    tasks.cancel_scope.cancel()
    asyncio.run(case())
    assert not server.REGISTRY._tickets
    assert store.read(record['profile_id'])['state']=='running'
    # Even after the thread exits, an interrupted native transaction requires
    # owner inspection/recovery. Reconnect cannot overlap uncertain cleanup.
    runtime.start(cfg)
    assert runtime.lease is None


@pytest.mark.parametrize('action',['set_value','invoke','select','scroll'])
def test_persistent_app_patterns_guard_and_no_physical_fallback(bridge,tmp_path,monkeypatch,action):
    # Reuse the fake COM/native-body harness; still no live provider semantics.
    from test_app_only import app
    harness=app.__wrapped__(bridge,monkeypatch)
    native,cfg,control,_,_,effects,checks=harness
    cfg['authorization_mode']='persistent'
    store=WindowsGrantStore(root=tmp_path/'owner'/'grants',protection=FakeProtection(),create=True)
    record=make_record(['notepad.exe'],['capture_window','app_actions'],FIXTURE_SECRET,7)
    store.create(record)
    runtime=PermissionRuntime(lambda:store)
    runtime.configure(cfg,{'TASKKIT_CLIENT_ID':record['profile_id'],'TASKKIT_CLIENT_SECRET':FIXTURE_SECRET})
    runtime.start(cfg)
    monkeypatch.setattr(server,'PERMISSIONS',runtime)
    monkeypatch.setattr(server,'desktop_health',lambda:{'usable_interactive_context':True})
    monkeypatch.setattr(server,'ask_local_consent',lambda _:pytest.fail('repeat dialog'))
    from win10_bridge_mcp import permission_store
    monkeypatch.setattr(permission_store,'WindowsGrantStore',lambda:store)
    with runtime.request(client()):
        ticket=server.capture_window(native.current.id).structuredContent['capture_id']
        result=server.app_control_action(native.current.id,ticket,'item',action,'Tiếng Việt 😀','none','small_increment',False)
    assert not result['bridge_physical_input_sent'] and not result['bridge_focus_requested']
    assert len(effects)==1 and checks and not any(checks)


def test_child_checks_revoked_store_before_semantic_effect(bridge,tmp_path,monkeypatch):
    from test_app_only import app
    native,cfg,control,_,_,effects,_=app.__wrapped__(bridge,monkeypatch)
    cfg['authorization_mode']='persistent'
    store=WindowsGrantStore(root=tmp_path/'owner'/'grants',protection=FakeProtection(),create=True)
    record=make_record(['notepad.exe'],['capture_window','app_actions'],FIXTURE_SECRET,7)
    store.create(record)
    runtime=PermissionRuntime(lambda:store)
    runtime.configure(cfg,{'TASKKIT_CLIENT_ID':record['profile_id'],'TASKKIT_CLIENT_SECRET':FIXTURE_SECRET})
    runtime.start(cfg)
    monkeypatch.setattr(server,'PERMISSIONS',runtime)
    monkeypatch.setattr(server,'desktop_health',lambda:{'usable_interactive_context':True})
    from win10_bridge_mcp import permission_store
    monkeypatch.setattr(permission_store,'WindowsGrantStore',lambda:store)
    raw=control.GetCurrentPattern
    def pattern(code):
        store.set_state(record['profile_id'],'revoked')
        return raw(code)
    control.GetCurrentPattern=pattern
    with runtime.request(client()):
        ticket=server.capture_window(native.current.id).structuredContent['capture_id']
        with pytest.raises(PermissionError):server.app_control_action(native.current.id,ticket,'item','invoke',dry_run=False)
    assert not effects


def test_storage_release_cannot_overwrite_concurrent_revoke(owner):
    runtime,store,_,record,_,_=owner
    expected=runtime.lease.record.copy()
    store.set_state(record['profile_id'],'revoked')
    store.release(record['profile_id'],expected)
    assert store.read(record['profile_id'])['state']=='revoked'


@pytest.mark.parametrize('capabilities',[['physical_input'],['app_actions'],['capture_window','file_save']])
def test_missing_data_permission_dependencies_require_explicit_selection(owner,capabilities):
    from win10_bridge_mcp.owner_permissions import enroll
    _,store,_,_,cfg,_=owner
    with pytest.raises(PermissionError,match='explicit owner selection'):
        enroll(store,cfg,['notepad.exe'],capabilities,7,owner_confirmed=True)


def test_owner_pause_after_grant_revoke_does_not_resurrect_profile(owner):
    runtime,store,_,record,_,_=owner
    store.set_state(record['profile_id'],'revoked')
    server.stop_permissions()
    assert store.read(record['profile_id'])['state']=='revoked'


def test_operation_cleanup_failure_cannot_release_running_marker(owner,monkeypatch):
    runtime,store,_,record,_,native=owner
    def fail(*args,**kwargs):raise OSError('fake owned-key cleanup failed')
    native.apply_keys=fail
    async def case():
        capture=await server.mcp.call_tool('capture_window',{'window_id':native.current.id})
        token=capture.structuredContent['capture_id']
        return await server.mcp.call_tool('press_key',{'window_id':native.current.id,'capture_id':token,'key':'a','dry_run':False})
    result=asyncio.run(case())
    assert result.isError and runtime.lease.unclean
    runtime.end()
    assert store.read(record['profile_id'])['state']=='running'


def test_eof_preview_owner_stop_race_cannot_release_grant(owner,monkeypatch):
    from win10_bridge_mcp import viewer
    runtime,store,_,record,_,_=owner
    runtime.end()
    owner_stop=threading.Event()
    class Closing:
        def is_set(self):return False
        def set(self):owner_stop.set()  # Owner closes immediately after teardown snapshot.
    async def case():
        async with server.connection_lifespan(server.mcp):
            monkeypatch.setattr(viewer,'_process',S(is_alive=lambda:True))
            monkeypatch.setattr(viewer,'_closed',Closing())
            monkeypatch.setattr(viewer,'_owner_stops',[owner_stop])
    asyncio.run(case())
    assert viewer.stopped() and owner_stop.is_set()
    assert store.read(record['profile_id'])['state'] in {'running','paused'}
    runtime.start(owner[4])
    assert runtime.lease is None


def test_legacy_worker_cannot_dispatch_after_mode_changes_to_persistent(owner):
    from win10_bridge_mcp.permissions import check_worker_authorization
    cfg=owner[4]
    with pytest.raises(PermissionError,match='requires an authenticated'):
        check_worker_authorization(None,cfg)


def test_status_clears_policy_after_config_change(owner):
    runtime,_,session,_,cfg,_=owner
    with runtime.request(session):
        status=server.bridge_status()
        assert status['physical_policy_authorized']
        assert status['capture']['window_policy_authorized']
        assert status['app_only']['policy_authorized']
        cfg['allowed']=frozenset({'notepad.exe','explorer.exe'})
        status=server.bridge_status()
        assert not status['authorization']['authenticated']
        assert not status['physical_policy_authorized']
        assert not status['capture']['window_policy_authorized']
