"""Opt-in timeout -> observation -> input regression, using only its own app."""
import argparse
import asyncio
import ctypes as ct
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def fixture(out):
    import tkinter as tk
    from win10_bridge_mcp import windows_native as n
    root=tk.Tk();root.title('TaskKit MCP timeout recovery fixture');root.geometry('560x240+350+250')
    tk.Label(root,text='TaskKit test — timeout recovery without owner restart').pack(pady=25)
    entry=tk.Entry(root);entry.pack(fill='x',padx=30,pady=20)
    root.update();hwnd=n.U.GetAncestor(root.winfo_id(),2)
    proc=ct.WINFUNCTYPE(ct.c_ssize_t,n.wt.HWND,n.wt.UINT,n.wt.WPARAM,n.wt.LPARAM)
    n.U.SetWindowLongPtrW.argtypes=(n.wt.HWND,ct.c_int,ct.c_void_p);n.U.SetWindowLongPtrW.restype=ct.c_void_p
    n.U.CallWindowProcW.argtypes=(ct.c_void_p,n.wt.HWND,n.wt.UINT,n.wt.WPARAM,n.wt.LPARAM);n.U.CallWindowProcW.restype=ct.c_ssize_t
    blocked=False
    @proc
    def callback(handle,msg,wp,lp):
        nonlocal blocked
        if msg==0x3d and not blocked:
            blocked=True;(out/'provider_entered').touch();time.sleep(6.5);(out/'provider_returned').touch()
        return n.U.CallWindowProcW(previous,handle,msg,wp,lp)
    previous=n.U.SetWindowLongPtrW(hwnd,-4,ct.cast(callback,ct.c_void_p))
    def flush():
        data={'pid':os.getpid(),'window_id':f'{os.getpid()}:{hwnd:x}','text':entry.get(),
              'entry':[entry.winfo_rootx(),entry.winfo_rooty(),entry.winfo_width(),entry.winfo_height()]}
        temp=out/'fixture.tmp';temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        os.replace(temp,out/'fixture.json');root.after(30,flush)
    flush();root.mainloop()


async def main(out):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    out=out.resolve();out.mkdir(parents=True,exist_ok=False)
    config=out/'config.json';config.write_text(json.dumps({'allow_processes':['python.exe'],'mouse_control_mode':'foreground_session'}))
    env=dict(os.environ,WIN10_BRIDGE_CONFIG=str(config),PYTHONUTF8='1')
    code=f"import sys,runpy;sys.path[:]={sys.path!r};sys.argv={[str(Path(__file__).resolve()),'--fixture',str(out)]!r};runpy.run_path({str(Path(__file__).resolve())!r},run_name='__main__')"
    app=subprocess.Popen([getattr(sys,'_base_executable',None) or sys.executable,'-c',code],env=env)
    def state():
        return json.loads((out/'fixture.json').read_text(encoding='utf-8'))
    try:
        for _ in range(100):
            if (out/'fixture.json').exists():break
            await asyncio.sleep(.05)
        wid=state()['window_id']
        async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','win10_bridge_mcp'],env=env)) as (r,w):
            async with ClientSession(r,w) as client:
                await client.initialize()
                async def call(name,args=None):
                    result=await client.call_tool(name,args or {})
                    assert not result.isError,(name,result)
                    return json.loads(result.content[0].text)
                # The fixture deliberately blocks UIA, not screenshot capture.
                old=await call('capture_window',{'window_id':wid})
                action=await call('capture_window',{'window_id':wid})
                started=time.monotonic()
                result=await client.call_tool('control_action',{'window_id':wid,'capture_id':action['capture_id'],
                    'automation_id':'disposable-no-action','action':'invoke','dry_run':False})
                elapsed=time.monotonic()-started
                assert result.isError and 'timed out' in result.content[0].text
                status=await call('bridge_status')
                assert not status['session_stopped'] and status['timeout_recovery']['recovery_required']
                rejected=await client.call_tool('press_key',{'window_id':wid,'capture_id':old['capture_id'],'key':'tab','dry_run':False})
                assert rejected.isError and 'unknown' in rejected.content[0].text.lower()
                for _ in range(80):
                    if (out/'provider_returned').exists():break
                    await asyncio.sleep(.05)
                assert (out/'provider_returned').exists()
                await call('capture_window',{'window_id':wid})
                status=await call('bridge_status');assert status['timeout_recovery']['recovery_required']
                wins=await call('inspect_windows');win=next(w for w in wins['windows'] if w['window_id']==wid)
                capture=await call('capture_window',{'window_id':wid})
                status=await call('bridge_status')
                assert not status['session_stopped'] and not status['timeout_recovery']['recovery_required']
                stale=await client.call_tool('press_key',{'window_id':wid,'capture_id':old['capture_id'],'key':'tab','dry_run':False})
                assert stale.isError and 'predates timeout' in stale.content[0].text
                box=state()['entry'];x,y=box[0]+40-win['rect']['x'],box[1]+10-win['rect']['y']
                await call('click_left',{'window_id':wid,'capture_id':capture['capture_id'],'x':x,'y':y,'dry_run':False})
                capture=await call('capture_window',{'window_id':wid})
                text='TaskKit tiếp tục sau timeout'
                await call('type_text',{'window_id':wid,'capture_id':capture['capture_id'],'text':text,'dry_run':False})
                for _ in range(40):
                    if state()['text']==text:break
                    await asyncio.sleep(.05)
                assert state()['text']==text and app.poll() is None
                report={'version':status['version'],'mutation_timeout_seconds':round(elapsed,3),
                        'timeout_does_not_cancel_session':True,'stale_input_rejected':True,
                        'inspection_then_capture_recovers':True,'physical_input_verified_after_recovery':True,
                        'owner_restart_requests':0,'uncertain_action_replays':0,'application_preserved':True}
                (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
                await call('emergency_release')
    finally:
        app.terminate();app.wait(5)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',action='store_true');p.add_argument('--fixture',type=Path)
    p.add_argument('--out',type=Path,default=Path.cwd()/'work/live-recovery-verification');args=p.parse_args()
    if args.fixture:fixture(args.fixture)
    elif args.run:asyncio.run(main(args.out))
    else:p.error('Explicit --run required; uses physical input only in its own disposable app')
