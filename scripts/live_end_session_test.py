"""Opt-in finish/handoff test. Uses physical input only in its own fixture."""
import argparse,asyncio,json,os,subprocess,sys,time
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(out):
    out=out.resolve();out.mkdir(parents=True,exist_ok=False)
    config=out/'config.json';config.write_text(json.dumps({'allow_processes':['python.exe'],'mouse_control_mode':'foreground_session'}))
    env=dict(os.environ,WIN10_BRIDGE_CONFIG=str(config),PYTHONUTF8='1')
    fixture=Path(__file__).with_name('live_mouse_fixture.py')
    app=subprocess.Popen([sys.executable,str(fixture),'--out',str(out),'--keep-open-on-escape'],env=env)
    def state():
        try:return json.loads((out/'fixture.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):return {}
    try:
        for _ in range(100):
            if state().get('pid'):break
            await asyncio.sleep(.05)
        async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','win10_bridge_mcp'],env=env)) as (r,w):
            async with ClientSession(r,w) as client:
                init=await client.initialize();assert 'end_control_session' in init.instructions
                async def call(name,args=None):
                    result=await client.call_tool(name,args or {})
                    assert not result.isError,(name,result)
                    return json.loads(result.content[0].text)
                wins=await call('inspect_windows');win=next(w for w in wins['windows'] if w['pid']==state()['pid']);wid=win['window_id']
                await call('show_live_view',{'window_id':wid})
                status=await call('bridge_status');assert status['control_indicator_active'] and status['live_view']['visible']
                old=await call('capture_window',{'window_id':wid})
                image=await call('capture_window',{'window_id':wid})
                box=state()['canvas'];x,y=box[0]+120-win['rect']['x'],box[1]+100-win['rect']['y']
                hold=asyncio.create_task(client.call_tool('mouse_action',{'window_id':wid,'capture_id':image['capture_id'],
                    'action':'hold','button':'left','x':x,'y':y,'duration_ms':4000,'dry_run':False}))
                for _ in range(60):
                    if any(e['kind']=='left_down' for e in state().get('events',[])):break
                    await asyncio.sleep(.03)
                assert any(e['kind']=='left_down' for e in state()['events'])
                started=time.monotonic();ended=await call('end_control_session')
                elapsed=time.monotonic()-started
                interrupted=await hold
                assert ended['ended'] and interrupted.isError and elapsed<3
                status=await call('bridge_status')
                assert status['session_stopped'] and not status['control_indicator_active'] and not status['live_view']['visible']
                assert status['session_lifecycle']['last_end_reason']=='completed'
                for _ in range(40):
                    if any(e['kind']=='left_up' for e in state().get('events',[])):break
                    await asyncio.sleep(.03)
                assert any(e['kind']=='left_up' for e in state()['events'])
                assert app.poll() is None
                stale=await client.call_tool('press_key',{'window_id':wid,'capture_id':old['capture_id'],'key':'tab','dry_run':False})
                assert stale.isError and 'Unknown' in stale.content[0].text
                current=await call('capture_window',{'window_id':wid})
                blocked=await client.call_tool('press_key',{'window_id':wid,'capture_id':current['capture_id'],'key':'tab','dry_run':False})
                assert blocked.isError and 'stopped' in blocked.content[0].text
                assert (await call('end_control_session'))['ended']
                # A second explicitly authorized fixture task can start normally.
                prepared=await call('prepare_control_session',{'window_id':wid,'new_task':True})
                assert prepared['restarted'] and prepared['status']=='captured'
                assert not prepared['requires_owner_confirmation']
                active=await call('prepare_control_session',{'window_id':wid})
                assert not active['restarted'] and active['status']=='captured'
                # Exercise app_control after reopening, only on our explicit fixture dialog.
                (out/'dialog.request').touch()
                dialog=None
                for _ in range(80):
                    windows=await call('inspect_windows')
                    dialog=next((w for w in windows['windows'] if w['title']=='TaskKit MCP Dialog test' and w['pid']==state()['pid']),None)
                    if dialog:break
                    await asyncio.sleep(.05)
                assert dialog, 'Fixture dialog missing'
                ready=await call('prepare_control_session',{'window_id':dialog['window_id']})
                # Foreground the fixture dialog with one harmless Tab; app_control itself
                # deliberately does not activate background app providers.
                await call('press_key',{'window_id':dialog['window_id'],
                           'capture_id':ready['capture']['capture_id'],'key':'tab','dry_run':False})
                ready=await call('prepare_control_session',{'window_id':dialog['window_id']})
                controls=(await call('inspect_controls',{'window_id':dialog['window_id']}))['controls']
                button=next(c for c in controls if c['control_type']==50000 and c['name']=='OK')
                args={'window_id':dialog['window_id'],'capture_id':ready['capture']['capture_id'],
                      'control_name':button['name'],'dry_run':False}
                assert (await call('app_control',args))['invoke_requested']
                for _ in range(80):
                    if any(e['kind']=='dialog_closed' for e in state().get('events',[])):break
                    await asyncio.sleep(.05)
                assert any(e['kind']=='dialog_closed' for e in state()['events'])
                await call('show_live_view',{'window_id':wid})
                assert not (await call('bridge_status'))['session_stopped']
                assert (await call('end_control_session',{'reason':'handoff'}))['ended']
                status=await call('bridge_status')
                assert status['session_lifecycle']['last_end_reason']=='handoff'
                report={'version':status['version'],'finish_interrupt_seconds':round(elapsed,3),
                        'held_button_released':True,'preview_and_indicator_closed':True,
                        'old_captures_invalidated':True,'post_finish_input_blocked':True,
                        'read_only_capture_available':True,'repeated_finish_safe':True,
                        'new_owner_task_and_handoff_verified':True,'app_control_after_prepare_verified':True,'application_preserved':True}
                (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
    finally:
        (out/'close.request').touch()
        try:app.wait(5)
        except subprocess.TimeoutExpired:app.terminate();app.wait(5)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true')
    parser.add_argument('--out',type=Path,default=Path.cwd()/'work/live-end-session-verification');args=parser.parse_args()
    if not args.run:parser.error('Explicit --run required; occupies the pointer only in its own disposable fixture')
    asyncio.run(main(args.out))
