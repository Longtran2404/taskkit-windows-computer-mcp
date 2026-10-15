import argparse,asyncio,base64,json,os,subprocess,sys,time
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

S=Path(__file__).resolve().parents[1]
O=None
C=None

def state():
    try:return json.loads((O/'fixture.json').read_text(encoding='utf8'))
    except (OSError,ValueError):return {}

async def main(out):
    global O,C
    O=out.resolve();O.mkdir(parents=True,exist_ok=True)
    C=O/'config.json';C.write_text(json.dumps({'allow_processes':['*'],'mouse_control_mode':'foreground_session'}))
    env=dict(os.environ,WIN10_BRIDGE_CONFIG=str(C),PYTHONUTF8='1')
    fixture=subprocess.Popen([sys.executable,str(S/'scripts/live_mouse_fixture.py'),'--out',str(O),'--keep-open-on-escape'],env=env)
    passed=[]
    try:
        for _ in range(100):
            if state().get('parent_pid')==fixture.pid or state().get('pid')==fixture.pid:break
            await asyncio.sleep(.05)
        async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','win10_bridge_mcp'],env=env)) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize()
                async def call(name,args=None):
                    result=await session.call_tool(name,args or {})
                    assert not result.isError,(name,result)
                    if result.content and result.content[0].type=='text':return json.loads(result.content[0].text),result
                    return {},result
                wins,_=await call('inspect_windows')
                win=next(w for w in wins['windows'] if w['pid']==state()['pid']);wid=win['window_id']
                monitors,_=await call('list_monitors');assert len(monitors['monitors'])>=1
                normal_controls,_=await call('inspect_controls',{'window_id':wid})
                assert isinstance(normal_controls['controls'],list)
                for monitor in ['all']+[m['monitor_id'] for m in monitors['monitors']]:
                    info,image=await call('capture_desktop',{'monitor_id':monitor})
                    assert info['image_width']>0 and info['image_height']>0 and 'capture_id' not in info
                    (O/f'desktop_{monitor}.png').write_bytes(base64.b64decode(image.content[1].data))
                passed.append('capture_all_and_each_monitor')
                await call('show_live_view',{'window_id':wid})
                (O/'dialog.request').touch()
                for _ in range(60):
                    windows,_=await call('inspect_windows')
                    parent=next(w for w in windows['windows'] if w['window_id']==wid)
                    if parent['blocked_by_window_id']:break
                    await asyncio.sleep(.05)
                assert not parent['enabled'] and parent['blocked_by_window_id']
                dialog_id=parent['blocked_by_window_id']
                parent_capture,_=await call('capture_window',{'window_id':wid})
                blocked=await session.call_tool('press_key',{'window_id':wid,'capture_id':parent_capture['capture_id'],'key':'enter','dry_run':False})
                assert blocked.isError and 'dialog' in blocked.content[0].text.lower()
                for _ in range(40):
                    current,_=await call('bridge_status')
                    if current['live_view'].get('frame_title')=='TaskKit MCP Dialog test':break
                    await asyncio.sleep(.1)
                assert current['live_view']['frame_title']=='TaskKit MCP Dialog test'
                meta,_=await call('capture_window',{'window_id':dialog_id})
                await call('press_key',{'window_id':dialog_id,'capture_id':meta['capture_id'],'key':'enter','dry_run':False})
                await asyncio.sleep(.2)
                windows,_=await call('inspect_windows')
                assert next(w for w in windows['windows'] if w['window_id']==wid)['enabled']
                passed.append('modal_detect_parent_refused_preview_follows_dialog_and_close')
                for monitor in [monitors['monitors'][0]['monitor_id'],'all']:
                    info,_=await call('show_live_view',{'source':'desktop','monitor_id':monitor,'fullscreen':True})
                    assert info['fullscreen'] and info['click_through'] and info['capture_excluded']
                    target=monitors['virtual_desktop'] if monitor=='all' else monitors['monitors'][0]
                    assert all(info[k]==target[k] for k in ('x','y','width','height')),(info,target)
                    for _ in range(30):
                        status,_=await call('bridge_status')
                        if status['live_view'].get('last_frame_ready'):break
                        await asyncio.sleep(.1)
                    assert status['live_view']['last_frame_ready']
                    from win10_bridge_mcp import windows_native as n
                    await asyncio.sleep(.4)
                    overlay,_=await call('bridge_status')
                    displays=overlay['control_indicator_displays']['monitors']
                    assert overlay['control_indicator_displays']['active'] and len(displays)==len(monitors['monitors'])
                    zorder=[]
                    @n.WNDENUMPROC
                    def collect(hwnd,_):zorder.append(int(hwnd));return True
                    n.U.EnumWindows(collect,0)
                    for display in displays:
                        assert n.U.IsWindowVisible(display['hwnd']) and not n.U.IsWindowEnabled(display['hwnd'])
                        r=n.RECT();assert n.U.GetWindowRect(display['hwnd'],n.ct.byref(r))
                        assert (r.left,r.top,r.right-r.left,r.bottom-r.top)==tuple(display[k] for k in ('x','y','width','height'))
                        assert zorder.index(display['hwnd'])<zorder.index(overlay['live_view']['hwnd']),('Indicator hidden behind fullscreen',display)
                    if monitor=='all':
                        screenshot,result=await call('capture_desktop')
                        from PIL import Image
                        from io import BytesIO
                        visible=Image.open(BytesIO(base64.b64decode(result.content[1].data))).convert('RGB')
                        area=state()['canvas']
                        pixel=(round((area[0]+20-screenshot['origin_x'])*screenshot['scale_x']),round((area[1]+30-screenshot['origin_y'])*screenshot['scale_y']))
                        assert max(abs(a-b) for a,b in zip(visible.getpixel(pixel),(30,53,83)))<8,('Preview recaptured or obscured underlying desktop',visible.getpixel(pixel))
                        box=state()['entry'];x,y=box[0]+100-win['rect']['x'],box[1]+12-win['rect']['y']
                        meta,_=await call('capture_window',{'window_id':wid})
                        await call('click_left',{'window_id':wid,'capture_id':meta['capture_id'],'x':x,'y':y,'dry_run':False})
                        meta,_=await call('capture_window',{'window_id':wid})
                        await call('type_text',{'window_id':wid,'capture_id':meta['capture_id'],'text':'Fullscreen xuyên chuột thành công','dry_run':False})
                        for _ in range(40):
                            if state().get('text')=='Fullscreen xuyên chuột thành công':break
                            await asyncio.sleep(.05)
                        assert state()['text']=='Fullscreen xuyên chuột thành công'
                passed.append('single_and_all_monitor_fullscreen_click_through')
                passed.append('indicator_on_every_monitor_above_fullscreen_without_focus')
                await call('show_live_view',{'window_id':wid,'source':'window','fullscreen':False})
                st,_=await call('bridge_status');assert not st['session_stopped'] and not st['live_view']['fullscreen']
                passed.append('switch_back_without_cancelling')
                await call('close_live_view');await call('start_control_session')
                await call('show_live_view',{'source':'desktop','fullscreen':True})
                from win10_bridge_mcp import windows_native as n
                box=state()['entry'];x,y=box[0]+100-win['rect']['x'],box[1]+12-win['rect']['y']
                meta,_=await call('capture_window',{'window_id':wid})
                await call('click_left',{'window_id':wid,'capture_id':meta['capture_id'],'x':x,'y':y,'dry_run':False})
                assert n.U.GetForegroundWindow()==int(wid.split(':')[1],16),'Fixture lost focus before Escape pulse'
                n._virtual_key(0x1B,True);await asyncio.sleep(.12);n._virtual_key(0x1B,False)
                for _ in range(40):
                    st,_=await call('bridge_status')
                    if st['session_stopped'] and not st['live_view']['visible']:break
                    await asyncio.sleep(.05)
                assert st['session_stopped'] and not st['live_view']['visible']
                passed.append('escape_closes_fullscreen_and_stops_input')
                await call('start_control_session');await call('emergency_release')
                report={'version':st['version'],'monitor_count':len(monitors['monitors']),'passed':passed,'artifacts':str(O)}
                (O/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
                print(json.dumps(report),flush=True)
    finally:
        (O/'close.request').touch()
        try:fixture.wait(timeout=5)
        except subprocess.TimeoutExpired:fixture.terminate()
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--out',type=Path,default=Path.cwd()/'work/live-desktop-verification')
    args=parser.parse_args()
    if not args.run:parser.error('Explicit --run required; this test uses physical input and desktop capture')
    asyncio.run(main(args.out))
