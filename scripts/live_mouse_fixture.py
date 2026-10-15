import argparse,ctypes,json,os,tkinter as tk,time
from pathlib import Path
from win10_bridge_mcp import windows_native as n
from win10_bridge_mcp import __version__
p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--keep-open-on-escape',action='store_true');a=p.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
root=tk.Tk();root.title(f'TaskKit MCP v{__version__} — Input test');root.geometry('760x470+300+180');root.configure(bg='#121c2d')
tk.Label(root,text=f'TaskKit.vn  •  MCP v{__version__}  •  Kiểm tra chuột / bàn phím',font=('Segoe UI',14,'bold'),bg='#121c2d',fg='white',pady=14).pack(fill='x')
canvas=tk.Canvas(root,bg='#1e3553',highlightthickness=0,height=270);canvas.pack(fill='both',expand=True,padx=18,pady=8)
canvas.create_text(360,80,text='Click · Right · Middle · Double · Drag · Wheel',fill='#e9f4ff',font=('Segoe UI',13))
entry=tk.Entry(root,font=('Segoe UI',13));entry.pack(fill='x',padx=18,pady=16)
entry.bind('<Control-a>',lambda e:(entry.selection_range(0,tk.END),'break')[1])
events=[]
dialog_shown=False
def record(kind,event=None,data=None):
 events.append({'kind':kind,'time':time.monotonic(),'x':getattr(event,'x',None),'y':getattr(event,'y',None),'state':getattr(event,'state',0),'data':data})
for kind,sequence in [('left_down','<ButtonPress-1>'),('left_up','<ButtonRelease-1>'),('right_down','<ButtonPress-3>'),('right_up','<ButtonRelease-3>'),('middle_down','<ButtonPress-2>'),('middle_up','<ButtonRelease-2>'),('double','<Double-Button-1>'),('drag','<B1-Motion>'),('wheel','<MouseWheel>')]:
 canvas.bind(sequence,lambda e,k=kind:record(k,e))
root.update()
# Observe raw wheel/X-button messages on this fixture's own canvas window only.
LRESULT=ctypes.c_ssize_t;PROC=ctypes.WINFUNCTYPE(LRESULT,n.wt.HWND,n.wt.UINT,n.wt.WPARAM,n.wt.LPARAM)
setproc=n.U.SetWindowLongPtrW;setproc.argtypes=(n.wt.HWND,ctypes.c_int,ctypes.c_void_p);setproc.restype=ctypes.c_void_p
n.U.CallWindowProcW.argtypes=(ctypes.c_void_p,n.wt.HWND,n.wt.UINT,n.wt.WPARAM,n.wt.LPARAM);n.U.CallWindowProcW.restype=LRESULT
handle=canvas.winfo_id();previous=None
@PROC
def observe(hwnd,msg,wp,lp):
 if msg in {0x020B,0x020C,0x020E}:record({0x020B:'x_down',0x020C:'x_up',0x020E:'horizontal_wheel'}[msg],data=(wp>>16)&0xffff)
 return n.U.CallWindowProcW(previous,hwnd,msg,wp,lp)
previous=setproc(handle,-4,ctypes.cast(observe,ctypes.c_void_p))
def rect(w):return [w.winfo_rootx(),w.winfo_rooty(),w.winfo_width(),w.winfo_height()]
def flush():
 global dialog_shown
 payload={'pid':os.getpid(),'parent_pid':os.getppid(),'title':root.title(),'canvas':rect(canvas),'entry':rect(entry),'events':events,'text':entry.get()}
 temp=out/'fixture.tmp';temp.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
 try:os.replace(temp,out/'fixture.json')
 except PermissionError:pass
 if (out/'close.request').exists():root.destroy();return
 if (out/'dialog.request').exists() and not dialog_shown:
  dialog_shown=True
  def show_dialog():
   n.U.MessageBoxW.argtypes=(n.wt.HWND,n.wt.LPCWSTR,n.wt.LPCWSTR,n.wt.UINT);n.U.MessageBoxW.restype=ctypes.c_int
   n.U.MessageBoxW(n.U.GetAncestor(root.winfo_id(),2),'Close this test dialog with OK.','TaskKit MCP Dialog test',0)
   record('dialog_closed')
  root.after(1,show_dialog)
 root.after(30,flush)
root.bind('<Escape>',lambda e:record('escape') if a.keep_open_on_escape else (record('escape'),root.after(180,root.destroy)))
root.protocol('WM_DELETE_WINDOW',root.destroy)
flush();root.mainloop()

