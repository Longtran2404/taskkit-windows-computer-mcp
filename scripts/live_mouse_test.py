"""Owner-run real stdio + native-input check on an isolated test window.
Run explicitly with --run. Never uses production CAD/Revit models.
"""
import argparse,asyncio,base64,json,os,subprocess,sys,time
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

def read_state(out):
 try:
  state=json.loads((out/'fixture.json').read_text(encoding='utf-8'));read_state.cached=state;return state
 except (FileNotFoundError,PermissionError,json.JSONDecodeError):return getattr(read_state,'cached',None)
async def main(out):
 out.mkdir(parents=True,exist_ok=True)
 cfg=out/'config.json';cfg.write_text(json.dumps({'allow_processes':['python.exe'],'mouse_control_mode':'foreground_session'}))
 fixture=subprocess.Popen([sys.executable,str(Path(__file__).with_name('live_mouse_fixture.py')),'--out',str(out),'--keep-open-on-escape'])
 try:
  for _ in range(100):
   state=read_state(out)
   if state and (state['pid']==fixture.pid or state.get('parent_pid')==fixture.pid):break
   await asyncio.sleep(.05)
  else:raise RuntimeError('Test fixture did not start')
  env=dict(os.environ,WIN10_BRIDGE_CONFIG=str(cfg),PYTHONUTF8='1')
  async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','win10_bridge_mcp'],env=env)) as (r,w):
   async with ClientSession(r,w) as session:
    await session.initialize()
    async def call(name,args):
     result=await session.call_tool(name,args)
     assert not result.isError,(name,result)
     return result
    wins=json.loads((await call('inspect_windows',{})).content[0].text)['windows']
    win=next(w for w in wins if w['title']==state['title'] and w['pid']==state['pid']);wid=win['window_id']
    async def capture(name=None):
     result=await call('capture_window',{'window_id':wid});meta=json.loads(result.content[0].text)
     if name:(out/name).write_bytes(base64.b64decode(next(c.data for c in result.content if c.type=='image')))
     return meta
    async def replace_fixture_text(text):
     current=read_state(out);px,py=point(current['entry'],150,12)
     meta=await capture();await call('click_left',{'window_id':wid,'capture_id':meta['capture_id'],'x':px,'y':py,'dry_run':False})
     meta=await capture();await call('type_text',{'window_id':wid,'capture_id':meta['capture_id'],'text':text,'replace_all':True,'dry_run':False})
     for _ in range(40):
      if read_state(out)['text']==text:return
      await asyncio.sleep(.05)
     raise AssertionError(('Fixture text mismatch',read_state(out)['text'],text))
    await capture('before.png');print('LIVE_FIXTURE_READY',flush=True)
    def point(box,dx,dy):return box[0]+dx-win['rect']['x'],box[1]+dy-win['rect']['y']
    x,y=point(state['canvas'],160,140);ex,ey=point(state['canvas'],350,210)
    results=[]
    cases=[('left','click','left','left_down',{}),('right','click','right','right_down',{}),('middle','click','middle','middle_down',{}),('double','double_click','left','double',{}),('x1','click','x1','x_down',{}),('x2','click','x2','x_down',{}),('drag','drag','left','drag',{'end_x':ex,'end_y':ey,'duration_ms':300}),('hold','hold','left','left_up',{'duration_ms':300}),('wheel','scroll','left','wheel',{'wheel_ticks':2}),('horizontal','scroll','left','horizontal_wheel',{'wheel_ticks':2,'wheel_axis':'horizontal'}),('ctrl_shift_drag','drag','left','drag',{'end_x':ex,'end_y':ey,'duration_ms':250,'modifiers':'ctrl+shift'})]
    for label,action,button,expected,extra in cases:
     state=read_state(out);before=len(state['events']);meta=await capture()
     tool={'left':'click_left','right':'click_right','middle':'click_middle','wheel':'scroll_mouse','horizontal':'scroll_mouse'}.get(label,'mouse_action')
     args={'window_id':wid,'capture_id':meta['capture_id'],'x':x,'y':y,'dry_run':False,**extra}
     if tool=='mouse_action':args.update(action=action,button=button)
     await call(tool,args)
     for _ in range(50):
      await asyncio.sleep(.04);state=read_state(out);events=state['events'][before:]
      if any(e['kind']==expected for e in events):break
     else:raise AssertionError((label,'Expected event missing',events))
     await asyncio.sleep(.15);events=read_state(out)['events'][before:]
     allowed={'left':{'left_down','left_up','double','drag'},'right':{'right_down','right_up'},'middle':{'middle_down','middle_up'},'x1':{'x_down','x_up'},'x2':{'x_down','x_up'}}[button] if action!='scroll' else {'wheel','horizontal_wheel'}
     button_events=[e for e in events if e['kind'].endswith(('_down','_up')) or e['kind'] in {'double','drag'}]
     assert all(e['kind'] in allowed for e in button_events),(label,'Unrelated button event',button_events)
     if label in {'x1','x2'}:assert any(e['kind']=='x_down' and e['data']==(1 if label=='x1' else 2) for e in events)
     if label=='ctrl_shift_drag':assert any(e['kind']=='drag' and e['state']&5==5 for e in events)
     if label=='hold':
      downs=[e for e in events if e['kind']=='left_down'];ups=[e for e in events if e['kind']=='left_up']
      assert downs and ups and ups[-1]['time']-downs[0]['time']>=.25
     results.append(label);print('PASS',label,flush=True)
     await asyncio.sleep(.25)
    state=read_state(out);x,y=point(state['entry'],150,12);meta=await capture()
    await call('mouse_action',{'window_id':wid,'capture_id':meta['capture_id'],'action':'click','x':x,'y':y,'dry_run':False})
    meta=await capture();text='TaskKit.vn — nhấp chuột và gõ tiếng Việt cực kì thành công.'
    await call('type_text',{'window_id':wid,'capture_id':meta['capture_id'],'text':text,'dry_run':False})
    await asyncio.sleep(.25);assert read_state(out)['text']==text
    results.append('unicode_text');await capture('after.png')
    status=json.loads((await call('bridge_status',{})).content[0].text)
    assert status['control_indicator_active'],'Visible input-session indicator missing'
    from PIL import ImageGrab
    ImageGrab.grab(all_screens=True).save(out/'desktop_indicator.png')
    # Send a real Windows Escape pulse to the currently active fixture.
    from win10_bridge_mcp import windows_native as native
    assert native.U.GetForegroundWindow()==int(wid.split(':')[1],16),'Fixture lost focus before Escape pulse'
    native._virtual_key(0x1B,True);await asyncio.sleep(.12);native._virtual_key(0x1B,False)
    await asyncio.sleep(.2)
    for _ in range(50):
     status=json.loads((await call('bridge_status',{})).content[0].text)
     if status['session_stopped'] and not status['control_indicator_active']:break
     await asyncio.sleep(.04)
    assert status['session_stopped'] and not status['control_indicator_active']
    await call('inspect_windows',{})
    stopped_capture=await capture()
    blocked=await session.call_tool('type_text',{'window_id':wid,'capture_id':stopped_capture['capture_id'],'text':'MUST NOT TYPE','dry_run':False});assert blocked.isError
    results.append('escape_stop')
    stopped_capture=await capture()
    # Only an explicit new task starts a new session; old tickets stay invalid.
    await call('start_control_session',{})
    stale=await session.call_tool('type_text',{'window_id':wid,'capture_id':stopped_capture['capture_id'],'text':'STALE','dry_run':False});assert stale.isError
    await replace_fixture_text('Restart sau ESC thành công')
    status=json.loads((await call('bridge_status',{})).content[0].text);assert status['control_indicator_active'] and not status['session_stopped']
    results.append('explicit_restart_and_stale_capture_rejection')
    # Repeat with F12, then a real preview close, within the same MCP process.
    assert native.U.GetForegroundWindow()==int(wid.split(':')[1],16),'Fixture lost focus before F12 pulse'
    native._virtual_key(0x7B,True);await asyncio.sleep(.12);native._virtual_key(0x7B,False);await asyncio.sleep(.2)
    status=json.loads((await call('bridge_status',{})).content[0].text);assert status['session_stopped']
    await call('start_control_session',{})
    await replace_fixture_text('Restart sau F12 thành công');results.append('f12_restart')
    await call('show_live_view',{'window_id':wid});await call('close_live_view',{})
    status=json.loads((await call('bridge_status',{})).content[0].text);assert status['session_stopped']
    await call('inspect_windows',{});await call('start_control_session',{})
    await replace_fixture_text('Restart sau đóng preview thành công');results.append('preview_close_restart')
    await capture('after_restart.png')
    await call('emergency_release',{})
    (out/'report.json').write_text(json.dumps({'passed':results,'count':len(results),'version':status['version']}),encoding='utf-8')
    print('ALL_LIVE_CHECKS_PASS',len(results),flush=True)
 finally:
  # Only the explicitly spawned test-fixture process belongs to this runner.
  (out/'close.request').touch()
  for _ in range(40):
   if fixture.poll() is not None:break
   await asyncio.sleep(.05)
  if fixture.poll() is None:fixture.terminate()
  fixture.wait(timeout=10)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',action='store_true');p.add_argument('--out',type=Path,default=Path.cwd()/'work/live-input-verification');a=p.parse_args()
 if not a.run:p.error('Explicit --run required; this test occupies physical input')
 asyncio.run(main(a.out.resolve()))

