"""Screen mode geometry/consent/transport with synthetic images, no real desktop."""
from dataclasses import replace
import asyncio
import pytest
from win10_bridge_mcp import server
from win10_bridge_mcp.capture_policy import Display, DesktopLayout, choose_region
from win10_bridge_mcp.policy import Rect


@pytest.fixture
def screens(bridge):
    native,cfg=bridge
    cfg['capture_modes']=['window','monitor','virtual_desktop','region']
    return native,cfg


@pytest.mark.parametrize('mode,args,expected',[
    ('monitor',{'monitor_id':'left'},Rect(-1280,0,0,720)),
    ('virtual_desktop',{},Rect(-1280,0,1920,1080)),
    ('region',{'left':-1200,'top':20,'width':100,'height':80},Rect(-1200,20,-1100,100)),
    ('region',{'left':1919,'top':1079,'width':1,'height':1},Rect(1919,1079,1920,1080))])
def test_physical_region_mapping_and_edge_bounds(screens,mode,args,expected):
    native,_=screens
    assert choose_region(mode,native.layout,**args)==expected


@pytest.mark.parametrize('args',[
    {'left':-1281,'top':0,'width':10,'height':10},
    {'left':1910,'top':0,'width':11,'height':10},
    {'left':0,'top':-1,'width':10,'height':10},
    {'left':0,'top':0,'width':0,'height':10},
    {'left':0,'top':0,'width':-1,'height':10},
    {'left':0,'top':0,'width':10,'height':-1},
    {'left':0,'top':0,'width':10,'height':1081}])
def test_invalid_region_refused_before_data_access(screens,args):
    native,_=screens
    with pytest.raises(ValueError): choose_region('region',native.layout,**args)


@pytest.mark.parametrize('mode,args',[('monitor',{'monitor_id':'missing'}),
    ('monitor',{'monitor_id':'left','width':1}),('region',{'monitor_id':'left','width':5,'height':5}),
    ('virtual_desktop',{'monitor_id':'left'}),('virtual_desktop',{'left':1}),('unknown',{})])
def test_explicit_mode_arguments_not_silently_reinterpreted(screens,mode,args):
    native,_=screens
    with pytest.raises(ValueError): choose_region(mode,native.layout,**args)


def test_large_capture_and_win32_overflow_refused():
    layout=DesktopLayout((Display('large',Rect(-10000,0,10000,10000),96,96),))
    with pytest.raises(ValueError,match='pixels'): choose_region('virtual_desktop',layout)
    with pytest.raises(ValueError,match='pixels'): choose_region('region',layout,left=0,top=0,width=5000,height=5000)
    enormous=DesktopLayout((Display('overflow',Rect(2**31,0,2**31+100,100),96,96),))
    with pytest.raises(ValueError,match='Win32'): choose_region('monitor',enormous,monitor_id='overflow')


@pytest.mark.parametrize('mode,args',[('monitor',{'monitor_id':'left'}),('virtual_desktop',{}),
    ('region',{'left':-1200,'top':30,'width':100,'height':100})])
def test_desktop_capture_scoped_consent_metadata_without_input_tokens(screens,monkeypatch,mode,args):
    native,cfg=screens
    prompts=[]
    monkeypatch.setattr(server,'ask_local_consent',lambda text:prompts.append(text) or True)
    result=server.capture_screen(mode,**args,dry_run=False)
    info=result.structuredContent
    assert info['mode']==mode
    assert info['capture_id'] is None
    assert info['input_authorization'] is False
    assert info['origin'][0] < 0
    assert info['timestamp_utc']
    assert info['display_layout']['monitors'][0]['dpi']==[144,144]
    assert info['may_include_other_apps']
    assert not info['gpu_viewport_verified']
    assert not server.REGISTRY._tickets
    assert len(prompts)==1
    assert 'other applications' in prompts[0] and 'SEND an image' in prompts[0]
    assert not server.CONSENT.armed(cfg)
    assert not server.APP_CONSENT.armed(cfg)
    # Observation IDs are never click authority, even for an allowlisted window.
    with pytest.raises(ValueError):
        server.mouse_action(native.current.id,info['observation_id'],'click',10,10)


def test_window_generic_mode_is_explicit_window_only_token(screens):
    native,_=screens
    result=server.capture_screen('window',window_id=native.current.id,dry_run=False)
    assert result.structuredContent['mode']=='window'
    assert result.structuredContent['window_id']==native.current.id
    assert result.structuredContent['capture_id'] in server.REGISTRY._tickets


def test_dry_run_discovers_target_without_pixels_or_consent(screens,monkeypatch):
    native,_=screens
    monkeypatch.setattr(server,'ask_local_consent',lambda _:pytest.fail('dry run consent'))
    monkeypatch.setattr(native,'capture_screen',lambda *_,**kw:pytest.fail('dry run captured desktop'))
    result=server.capture_screen('region',left=-100,top=0,width=100,height=100)
    assert result['dry_run'] and not result['image_transferred']
    targets=server.inspect_capture_targets()
    assert targets['virtual_desktop']['left']==-1280
    assert len(targets['monitors'])==2
    assert server.CAPTURE_CONSENT.scope is None


def test_local_mode_enable_is_not_data_sharing_consent(screens,monkeypatch):
    native,cfg=screens
    monkeypatch.setattr(server,'ask_local_consent',lambda _:False)
    with pytest.raises(PermissionError): server.capture_screen('virtual_desktop',dry_run=False)
    cfg['capture_modes']=['window']
    with pytest.raises(PermissionError): server.capture_screen('virtual_desktop',dry_run=False)
    assert not server.REGISTRY._tickets


@pytest.mark.parametrize('fault',['stop','layout','dpi','timeout','crash','dimensions','config'])
def test_desktop_capture_faults_return_no_image_or_ticket(screens,monkeypatch,fault):
    native,cfg=screens
    original=native.capture_screen
    def capture(rect,layout,**kwargs):
        if fault=='timeout': raise TimeoutError('screen worker deadline')
        if fault=='crash': raise RuntimeError('screen worker crash')
        result=original(rect,layout,**kwargs)
        if fault=='stop': native.SESSION_STOP.set()
        if fault=='layout':
            d=layout.displays[0]; native.layout=replace(layout,displays=(replace(d,rect=Rect(-1300,0,0,720)),layout.displays[1]))
        if fault=='dpi':
            d=layout.displays[0]; native.layout=replace(layout,displays=(replace(d,dpi_x=192,dpi_y=192,scale_percent=200),layout.displays[1]))
        if fault=='config':
            changed=dict(cfg,capture_modes=['window'])
            monkeypatch.setattr(server,'load_config',lambda:changed)
        if fault=='dimensions':
            from PIL import Image
            from io import BytesIO
            data=BytesIO(); Image.new('RGB',(1,1)).save(data,'PNG')
            result=data.getvalue(),result[1],result[2]
        return result
    monkeypatch.setattr(native,'capture_screen',capture)
    result=asyncio.run(server.mcp.call_tool('capture_screen',{'mode':'monitor','monitor_id':'left','dry_run':False}))
    assert result.isError
    assert all(c.type=='text' for c in result.content)
    assert not server.REGISTRY._tickets


def test_capture_scope_expiry_region_change_and_owner_decline(screens,monkeypatch):
    _,cfg=screens
    dialogs=[]
    monkeypatch.setattr(server,'ask_local_consent',lambda text:dialogs.append(text) or True)
    args=dict(mode='region',left=-100,top=0,width=100,height=100,dry_run=False)
    server.capture_screen(**args); server.capture_screen(**args)
    assert len(dialogs)==1
    server.CAPTURE_CONSENT.expires=0
    server.capture_screen(**args)
    assert len(dialogs)==2
    server.capture_screen(**dict(args,left=0))
    assert len(dialogs)==3
    assert cfg['mouse_control_mode']=='foreground_session'
    assert not server.CONSENT.armed(cfg)


def test_stop_during_desktop_image_encode_discards_response(screens,monkeypatch):
    native,_=screens
    original=server.base64.b64encode
    def encode(value): native.SESSION_STOP.set(); return original(value)
    monkeypatch.setattr(server.base64,'b64encode',encode)
    with pytest.raises(InterruptedError): server.capture_screen('monitor',monitor_id='left',dry_run=False)
    assert not server.REGISTRY._tickets


@pytest.mark.parametrize('mode',['window','monitor','virtual_desktop','region'])
def test_every_capture_mode_obeys_stop_before_access(screens,mode):
    native,_=screens
    native.SESSION_STOP.set()
    with pytest.raises(InterruptedError):
        server.capture_screen(mode,window_id=native.current.id if mode=='window' else '',
                              monitor_id='left' if mode=='monitor' else '',width=10 if mode=='region' else 0,
                              height=10 if mode=='region' else 0,dry_run=False)


def test_window_failure_never_falls_back_to_desktop(screens,monkeypatch):
    native,_=screens
    monkeypatch.setattr(native,'capture_window',lambda *_,**kw:(_ for _ in ()).throw(RuntimeError('PrintWindow failed')))
    monkeypatch.setattr(native,'capture_screen',lambda *_,**kw:pytest.fail('silent desktop fallback'))
    with pytest.raises(RuntimeError): server.capture_screen('window',window_id=native.current.id,dry_run=False)


def test_desktop_layout_rejects_bad_scale_ids_and_rect():
    for displays in [(),(Display('x',Rect(0,0,0,10),96,96),),
                     (Display('x',Rect(0,0,10,10),0,96),),
                     (Display('x',Rect(0,0,10,10),96,96),Display('x',Rect(10,0,20,10),96,96))]:
        with pytest.raises(ValueError): DesktopLayout(displays)


def test_capture_disabled_list_and_bad_config(monkeypatch,tmp_path):
    import json
    from win10_bridge_mcp.config import load_config
    path=tmp_path/'cfg.json'; monkeypatch.setenv('WIN10_BRIDGE_CONFIG',str(path))
    path.write_text(json.dumps({'capture_modes':[]}))
    assert load_config()['capture_modes']==[]
    for value in [['monitor','monitor'],['fullscreen'],'monitor',[42]]:
        path.write_text(json.dumps({'capture_modes':value}))
        with pytest.raises(ValueError): load_config()
    path.write_text(json.dumps({'capture_consent_mode':'remote_auto'}))
    with pytest.raises(ValueError): load_config()


def test_capture_session_status_has_no_stale_scope(screens):
    server.capture_screen('region',left=-100,top=0,width=100,height=100,dry_run=False)
    status=server.bridge_status()['capture']
    assert status['consent_session_armed']
    assert status['consent_scope'][0]=='region'
    assert status['consent_remaining_seconds'] > 0
    server.CAPTURE_CONSENT.expires=0
    status=server.bridge_status()['capture']
    assert not status['consent_session_armed']
    assert status['consent_scope'] is None


def test_capture_status_invalidates_mode_list_changes(screens,monkeypatch):
    _,cfg=screens
    server.capture_screen('region',left=-100,top=0,width=100,height=100,dry_run=False)
    changed=dict(cfg,capture_modes=['window'])
    monkeypatch.setattr(server,'load_config',lambda:changed)
    status=server.bridge_status()['capture']
    assert not status['consent_session_armed']
    assert status['consent_scope'] is None
    assert status['backends_by_mode']['window']=='PrintWindow'
    assert status['backends_by_mode']['region']=='GDI BitBlt'
