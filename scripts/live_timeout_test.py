"""Opt-in, read-only hung-provider regression on a disposable Windows fixture."""
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
    root=tk.Tk();root.title('TaskKit MCP disposable hung-provider test');root.geometry('460x180+350+250')
    tk.Label(root,text='TaskKit test only — temporary blocked UIA provider').pack(pady=30)
    root.update();hwnd=n.U.GetAncestor(root.winfo_id(),2)
    proc=ct.WINFUNCTYPE(ct.c_ssize_t,n.wt.HWND,n.wt.UINT,n.wt.WPARAM,n.wt.LPARAM)
    n.U.SetWindowLongPtrW.argtypes=(n.wt.HWND,ct.c_int,ct.c_void_p);n.U.SetWindowLongPtrW.restype=ct.c_void_p
    n.U.CallWindowProcW.argtypes=(ct.c_void_p,n.wt.HWND,n.wt.UINT,n.wt.WPARAM,n.wt.LPARAM);n.U.CallWindowProcW.restype=ct.c_ssize_t
    @proc
    def callback(handle,msg,wp,lp):
        if msg==0x3d:  # Simulate a provider that never returns WM_GETOBJECT.
            (out/'provider_entered').touch();time.sleep(60)
        return n.U.CallWindowProcW(previous,handle,msg,wp,lp)
    previous=n.U.SetWindowLongPtrW(hwnd,-4,ct.cast(callback,ct.c_void_p))
    (out/'fixture.json').write_text(json.dumps({'pid':os.getpid(),'window_id':f'{os.getpid()}:{hwnd:x}'}))
    root.mainloop()


async def main(out):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    from win10_bridge_mcp import windows_native as n
    out=out.resolve();out.mkdir(parents=True,exist_ok=False)
    config=out/'config.json';config.write_text(json.dumps({'allow_processes':['python.exe'],'mouse_control_mode':'disabled'}))
    env=dict(os.environ,WIN10_BRIDGE_CONFIG=str(config),PYTHONUTF8='1')
    # Own the actual fixture process, not a Windows venv redirector.
    code=f"import sys,runpy;sys.path[:]={sys.path!r};sys.argv={[str(Path(__file__).resolve()),'--fixture',str(out)]!r};runpy.run_path({str(Path(__file__).resolve())!r},run_name='__main__')"
    app=subprocess.Popen([getattr(sys,'_base_executable',None) or sys.executable,'-c',code],env=env)
    try:
        for _ in range(100):
            if (out/'fixture.json').exists():break
            await asyncio.sleep(.05)
        wid=json.loads((out/'fixture.json').read_text())['window_id']
        async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','win10_bridge_mcp'],env=env)) as (r,w):
            async with ClientSession(r,w) as client:
                await client.initialize()
                started=time.monotonic()
                pending=asyncio.create_task(client.call_tool('inspect_controls',{'window_id':wid}))
                workers=set()
                while not pending.done():
                    result=await client.call_tool('bridge_status')
                    data=json.loads(result.content[0].text)
                    workers.update(o['worker_pid'] for o in data['native_operations']['active_operations'])
                    await asyncio.sleep(.05)
                error=await pending
                elapsed=time.monotonic()-started
                assert error.isError and 'timed out' in error.content[0].text
                assert 4.5<elapsed<8 and workers
                assert (out/'provider_entered').exists(), 'Fixture did not block the provider'
                result=await client.call_tool('inspect_windows')
                assert not result.isError and app.poll() is None
                result=await client.call_tool('bridge_status');data=json.loads(result.content[0].text)
                assert not data['native_operations']['active_operations']
                assert not data['native_operations']['last_failure']['result_unknown']
                for pid in workers:
                    handle=n.K.OpenProcess(0x1000,False,pid)
                    if handle:
                        n.K.GetExitCodeProcess.argtypes=(n.wt.HANDLE,ct.POINTER(n.wt.DWORD))
                        n.K.GetExitCodeProcess.restype=n.wt.BOOL
                        code=n.wt.DWORD()
                        try:
                            assert n.K.GetExitCodeProcess(handle,ct.byref(code))
                            assert code.value!=259,'Blocked worker process is still running'
                        finally:n.K.CloseHandle(handle)
                report={'version':data['version'],'provider_timeout_seconds':round(elapsed,3),
                        'mcp_responds_after_timeout':True,'worker_processes_reaped':True,
                        'application_preserved':True,'physical_input_sent':False}
                (out/'report.json').write_text(json.dumps(report,indent=2))
                print(json.dumps(report),flush=True)
    finally:
        app.terminate();app.wait(5)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',action='store_true');p.add_argument('--fixture',type=Path)
    p.add_argument('--out',type=Path,default=Path.cwd()/'work/live-timeout-verification');args=p.parse_args()
    if args.fixture:fixture(args.fixture)
    elif args.run:asyncio.run(main(args.out))
    else:p.error('Explicit --run required; opens only a disposable test application')
