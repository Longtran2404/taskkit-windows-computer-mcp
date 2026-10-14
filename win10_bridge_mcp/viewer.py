"""Local preview. Closing permanently stops this process; opening never rearms."""
from __future__ import annotations

from io import BytesIO
import queue
import threading
import multiprocessing
import time

STOP = threading.Event()
_lock = threading.Lock()
_process = None
_closed = threading.Event()
_ready = threading.Event()
_window_id = None
_starting_event = None
_owner_stop = threading.Event()
_owner_stops = []


def close_viewer():
    STOP.set()
    _owner_stop.set()
    _closed.set()


def disconnect_viewer():
    """End transport-owned preview without turning orderly EOF into owner stop."""
    global _process, _closed, _starting_event
    with _lock:
        old_closed = _closed
        owner_stopped = bool(STOP.is_set() or any(event.is_set() for event in _owner_stops))
        _process = None
        if not owner_stopped:
            _closed = threading.Event()
        if _starting_event is not None:
            _starting_event.set()
        old_closed.set()
        _starting_event = None
        return owner_stopped


def stopped():
    return (STOP.is_set() or any(event.is_set() for event in _owner_stops) or _closed.is_set() or
            (_process is not None and not _process.is_alive()))


def has_preview_activity():
    return _process is not None or _starting_event is not None


def ensure_viewer(window_id, allowed):
    if stopped():
        raise InterruptedError("Preview stopped; restart bridge locally to resume")
    if _process is not None and _process.is_alive():
        if _window_id != window_id:
            raise RuntimeError("Preview targets another window; close and reopen it for this target")
        return
    show_viewer(window_id, allowed)


def show_viewer(window_id, allowed, *, authorization=None, guard=lambda: None):
    global _process, _closed, _ready, _window_id, _starting_event, _owner_stop
    with _lock:
        if stopped():
            raise InterruptedError("Preview stop is permanent; restart bridge locally")
        from . import windows_native as native
        native.enable_session_stop()
        native._stop_if_needed()
        guard()
        if _process is not None and _process.is_alive():
            raise RuntimeError("Close the current preview before opening another")
        ctx = multiprocessing.get_context("spawn")
        closed = ctx.Event()
        ready = ctx.Event()
        _closed, _ready, _starting_event = closed, ready, closed
        _owner_stop = ctx.Event()
        _owner_stops.append(_owner_stop)  # Retain owner intent across EOF teardown races.
        errors = ctx.Queue()
        # A non-daemon preview may spawn disposable PrintWindow workers.
        candidate = ctx.Process(target=_run, args=(window_id, allowed, closed, ready, errors, authorization, _owner_stop))
        try:
            native._stop_if_needed()  # A simultaneous stop closes the NEW event.
            guard()
            candidate.start()
            _process = candidate
            _starting_event = None
            _window_id = window_id
            deadline = time.monotonic() + 5
            while not ready.wait(0.02):
                native._stop_if_needed()
                guard()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Preview startup timed out")
            if closed.is_set():
                try:
                    startup_error = errors.get(timeout=0.1)
                except queue.Empty:
                    raise InterruptedError("Preview closed during startup")
                raise RuntimeError("Preview startup failed: " + startup_error)
            native._stop_if_needed()
            guard()
            if stopped():
                raise InterruptedError("Preview stopped during startup")
        except Exception:
            closed.set()
            _starting_event = None
            if candidate.is_alive():
                candidate.terminate()
                candidate.join(0.25)
            # Owner/native stop keeps its latch; permission/EOF cancellation
            # only tears down this preview, without rearming any permission.
            raise
    return {"visible": True, "window_id": window_id, "close_key": "Esc",
            "note": "Local live preview only; physical mouse uses the target window"}


def _run(window_id, allowed, closed, ready, errors, authorization=None, owner_stop=None):
    global _closed
    _closed = closed
    root = None
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
        from . import windows_native as native
        win = native.get_window(window_id, allowed)
        def permission_check():
            if authorization is not None:
                from .permissions import check_worker_authorization
                from .config import load_config
                check_worker_authorization(dict(authorization, exe=win.exe), load_config())
        permission_check()
        root = tk.Tk()
        root.title("Win10 Bridge — Màn hình đang sử dụng — Esc để tắt")
        root.geometry("1000x680")
        root.minsize(480, 320)
        root.configure(bg="#141923")
        tk.Label(root, text="ĐANG XEM CỬA SỔ  •  Esc: tắt màn hình và dừng thao tác",
                 bg="#202938", fg="#ffffff", pady=12).pack(fill="x")
        status = tk.Label(root, text=win.title, bg="#141923", fg="#b9c9df")
        status.pack(fill="x", pady=6)
        canvas = tk.Label(root, bg="#0b1018")
        canvas.pack(fill="both", expand=True, padx=12, pady=12)
        def owner_close():
            if owner_stop is not None:
                owner_stop.set()
            closed.set()
        root.bind("<Escape>", lambda _: owner_close())
        root.protocol("WM_DELETE_WINDOW", owner_close)
        frames = queue.Queue(maxsize=1)

        def capture():
            while not closed.is_set():
                try:
                    permission_check()
                    current = native.get_window(window_id, allowed)
                    if authorization is None:
                        png, method, blank = native.capture_window(current)
                    else:
                        from .config import load_config
                        def frame_guard():
                            if closed.is_set():
                                raise InterruptedError("Preview connection ended")
                            permission_check()
                            native.check_window(current)
                        cfg = load_config()
                        png, method, blank = native.capture_window(current, guard=frame_guard,
                            deadline=authorization["deadline"], authorization={
                                "mode_key": "authorization_mode", "mode": "persistent",
                                "allowed": sorted(cfg["allowed"]),
                                "persistent": dict(authorization, exe=current.exe)})
                    frame = (png if not blank else None, current.title if not blank else "Không lấy được hình hợp lệ")
                except Exception as exc:
                    frame = (None, str(exc))
                try:
                    frames.put_nowait(frame)
                except queue.Full:
                    pass
                closed.wait(0.25)

        def tick():
            try:
                permission_check()
            except Exception:
                owner_close()
            if (native.U.GetAsyncKeyState(0x1B) & 0x8000 or
                    native.U.GetAsyncKeyState(0x7B) & 0x8000):
                owner_close()
            if closed.is_set():
                root.destroy()
                return
            try:
                png, title = frames.get_nowait()
                status.configure(text=title)
                if png:
                    with Image.open(BytesIO(png)) as image:
                        image.thumbnail((max(1, canvas.winfo_width()), max(1, canvas.winfo_height())))
                        photo = ImageTk.PhotoImage(image, master=root)
                    canvas.configure(image=photo)
                    canvas.image = photo
                else:
                    canvas.configure(image="")
                    canvas.image = None
            except queue.Empty:
                pass
            root.after(30, tick)

        threading.Thread(target=capture, daemon=True).start()
        root.after(30, tick)
        ready.set()
        root.mainloop()
    except Exception as exc:
        if owner_stop is not None:
            owner_stop.set()
        errors.put(str(exc))
        closed.set()
        ready.set()
    finally:
        closed.set()


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


if __name__ == "__main__":
    main()
