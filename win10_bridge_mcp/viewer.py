"""Local live window preview. Closing stops input until an explicit new session."""
from __future__ import annotations

from io import BytesIO
import queue
import threading
import atexit

STOP = threading.Event()
_lock = threading.Lock()
_process = None
_closed = threading.Event()
_ready = threading.Event()
_window_id = None
_requests = queue.Queue()
_view_state = {}
_state_lock = threading.Lock()


def status():
    with _state_lock:
        return dict(_view_state, visible=_process is not None and _process.is_alive() and not _closed.is_set())


def close_viewer():
    STOP.set()
    _closed.set()


def stopped():
    return STOP.is_set() or _closed.is_set() or (_process is not None and not _process.is_alive())


def reset_for_new_session():
    global _process, _closed, _ready, _window_id
    with _lock:
        close_viewer()
        if _process is not None:
            _process.join(2)
            if _process.is_alive():
                raise RuntimeError("Previous preview has not exited; session remains stopped")
        _process = None
        _closed = threading.Event()
        _ready = threading.Event()
        _window_id = None
        STOP.clear()


def ensure_viewer(window_id, allowed):
    if stopped():
        raise InterruptedError("Preview was closed; start_control_session requires a new owner-authorized task")
    if _process is not None and _process.is_alive():
        if _window_id != window_id:
            raise RuntimeError("Preview targets another window; close and reopen it for this target")
        return
    show_viewer(window_id, allowed)


def show_viewer(window_id, allowed, source='window', monitor_id='all', fullscreen=False):
    global _process, _closed, _ready, _window_id, _requests, _view_state
    options = {'window_id': window_id, 'source': source, 'monitor_id': monitor_id, 'fullscreen': fullscreen}
    with _lock:
        if _process is not None and _process.is_alive():
            done, result = threading.Event(), {}
            _requests.put((options, done, result))
            if not done.wait(5):
                raise RuntimeError('Preview update timed out')
            if 'error' in result:
                raise RuntimeError(result['error'])
            _window_id = window_id
            return status()
        STOP.clear()
        # Tk is created and serviced exclusively by this GUI thread. Avoid a
        # dependence on a spawned interpreter from the Windows MCP stdio host.
        _closed = threading.Event()
        _ready = threading.Event()
        errors = queue.Queue()
        _requests = queue.Queue()
        _view_state = {}
        _process = threading.Thread(target=_run, args=(options, allowed, _closed, _ready, errors, _requests, _view_state), daemon=True)
        _process.start()
        _window_id = window_id
        if not _ready.wait(5):
            close_viewer()
            raise RuntimeError("Preview startup timed out")
        if _closed.is_set():
            _process.join(1)
            raise RuntimeError(errors.get(timeout=1) if not errors.empty() else "Preview closed during startup")
    return status()


def _run(options, allowed, closed, ready, errors, requests, state):
    root = None
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
        from . import windows_native as native, desktop
        settings, settings_lock = {}, threading.Lock()
        root = tk.Tk()
        root.title("TaskKit MCP — Live view — ESC to cancel")
        root.geometry("1000x680")
        root.minsize(480, 320)
        root.configure(bg="#141923")
        toolbar = tk.Frame(root, bg='#202938')
        toolbar.pack(fill='x')
        tk.Label(toolbar, text='TaskKit MCP  •  ESC to cancel', bg='#202938', fg='white', pady=8).pack(side='left', padx=12)
        status = tk.Label(root, text='Preparing view…', bg="#141923", fg="#b9c9df")
        status.pack(fill="x", pady=6)
        canvas = tk.Label(root, bg="#0b1018")
        canvas.pack(fill="both", expand=True)
        root.bind("<Escape>", lambda _: closed.set())
        root.protocol("WM_DELETE_WINDOW", closed.set)
        frames = queue.Queue(maxsize=1)

        def apply_options(value):
            if value['source'] not in {'window', 'desktop'}:
                raise ValueError('source must be window or desktop')
            if value['source'] == 'desktop' and '*' not in allowed:
                raise PermissionError('Desktop preview requires owner-authorized all applications')
            if value['source'] == 'window':
                native.get_window(value['window_id'], allowed)
            bounds = desktop.monitor_bounds(desktop.list_monitors(), value['monitor_id'])
            root.overrideredirect(value['fullscreen'])
            if not value['fullscreen']:
                root.geometry('1000x680')
            root.update_idletasks()
            hwnd = native.U.GetAncestor(root.winfo_id(), 2)
            placement = desktop.configure_preview(hwnd, value['fullscreen'], bounds, value['source'] == 'desktop')
            with settings_lock:
                sequence = settings.get('sequence', 0) + 1
                settings.update(value, sequence=sequence)
            with _state_lock:
                state.update(value, visible=True, close_key='Esc/F12', hwnd=int(hwnd),
                             last_frame_ready=False, frame_title='Preparing view…', **placement)
                state.pop('last_error', None)
            canvas.configure(image='')
            canvas.image = None

        def change_view(**changes):
            with settings_lock:
                updated = {key: settings[key] for key in ('window_id', 'source', 'monitor_id', 'fullscreen')}
            updated.update(changes)
            try: apply_options(updated)
            except Exception as exc: status.configure(text=str(exc))

        tk.Button(toolbar, text='Fullscreen (F11)', command=lambda: change_view(fullscreen=True)).pack(side='right', padx=4)
        tk.Button(toolbar, text='Windowed', command=lambda: change_view(fullscreen=False)).pack(side='right', padx=4)
        if '*' in allowed:
            tk.Button(toolbar, text='All screens', command=lambda: change_view(source='desktop', monitor_id='all')).pack(side='right', padx=4)
        root.bind('<F11>', lambda _: change_view(fullscreen=not settings['fullscreen']))
        apply_options(options)

        def capture():
            while not closed.is_set():
                with settings_lock:
                    selected = dict(settings)
                try:
                    if selected['source'] == 'desktop':
                        png, meta = desktop.capture(selected['monitor_id'])
                        frame = (selected['sequence'], png, f"Desktop · {selected['monitor_id']} · {meta['desktop_width']} × {meta['desktop_height']}")
                    else:
                        windows = native.enumerate_windows(allowed)
                        current = next(w for w in windows if w.id == selected['window_id'])
                        details = native.window_details(current, windows)
                        if details['blocked_by_window_id']:
                            current = next(w for w in windows if w.id == details['blocked_by_window_id'])
                        png, method, blank = native.capture_window(current)
                        frame = (selected['sequence'], png if not blank else None, current.title if not blank else 'Unsupported window capture')
                except Exception as exc:
                    frame = (selected['sequence'], None, str(exc))
                try:
                    frames.put_nowait(frame)
                except queue.Full:
                    pass
                closed.wait(0.25)

        def tick():
            if native.U.GetAsyncKeyState(0x1B) & 0x8000 or native.U.GetAsyncKeyState(0x7B) & 0x8000 or native.SESSION_STOP.is_set():
                closed.set()
            if closed.is_set():
                canvas.configure(image="")
                canvas.image = None
                root.destroy()
                return
            try:
                value, done, result = requests.get_nowait()
                try: apply_options(value)
                except Exception as exc: result['error'] = str(exc)
                finally: done.set()
            except queue.Empty:
                pass
            try:
                sequence, png, title = frames.get_nowait()
                if sequence != settings['sequence']:
                    root.after(30, tick)
                    return
                status.configure(text=title)
                if png:
                    with Image.open(BytesIO(png)) as image:
                        size = (max(1, canvas.winfo_width()), max(1, canvas.winfo_height()))
                        if settings['fullscreen']:
                            ratio = min(size[0]/image.width, size[1]/image.height)
                            image = image.resize((max(1, round(image.width*ratio)), max(1, round(image.height*ratio))), Image.Resampling.LANCZOS)
                        else:
                            image.thumbnail(size)
                        photo = ImageTk.PhotoImage(image, master=root)
                    canvas.configure(image=photo)
                    canvas.image = photo
                else:
                    canvas.configure(image="")
                    canvas.image = None
                with _state_lock:
                    state['last_frame_ready'] = bool(png)
                    state['frame_title'] = title
            except queue.Empty:
                pass
            root.after(30, tick)

        threading.Thread(target=capture, daemon=True).start()
        root.after(30, tick)
        ready.set()
        root.mainloop()
    except Exception as exc:
        errors.put(str(exc))
        closed.set()
        ready.set()
    finally:
        closed.set()
        # All Tk wrappers and their cyclic references must be released on the
        # GUI thread, never by a later GC pass on the MCP request thread.
        if root is not None:
            try: root.destroy()
            except Exception: pass
        root = canvas = status = toolbar = tick = capture = apply_options = change_view = None
        import gc
        gc.collect()


def main():
    """Standalone preview, without an MCP client or screenshot transmission."""
    from .server import load_config
    from . import windows_native as native
    import tkinter as tk
    from tkinter import ttk
    allowed = load_config()["allowed"]
    windows = native.enumerate_windows(allowed)
    if not windows:
        raise RuntimeError("Open an allowed application first (default: Notepad)")
    picker = tk.Tk()
    picker.title("Win10 Bridge — Chọn cửa sổ")
    picker.geometry("620x140")
    tk.Label(picker, text="Chọn cửa sổ để xem trực tiếp trên máy:").pack(pady=12)
    choices = ttk.Combobox(picker, state="readonly", width=75,
                          values=[f"{w.exe} — {w.title}" for w in windows])
    choices.current(0)
    choices.pack()
    selected = []
    def choose():
        selected.append(windows[choices.current()].id)
        picker.destroy()
    ttk.Button(picker, text="Mở màn hình", command=choose).pack(pady=12)
    picker.bind("<Escape>", lambda _: picker.destroy())
    picker.mainloop()
    if selected:
        show_viewer(selected[0], allowed)
        _process.join()


def _shutdown():
    close_viewer()
    if _process is not None and _process is not threading.current_thread():
        _process.join(2)


atexit.register(_shutdown)


if __name__ == "__main__":
    main()
