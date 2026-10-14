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


def close_viewer():
    STOP.set()
    _closed.set()


def stopped():
    return STOP.is_set() or _closed.is_set() or (_process is not None and not _process.is_alive())


def ensure_viewer(window_id, allowed):
    if stopped():
        raise InterruptedError("Preview stopped; restart bridge locally to resume")
    if _process is not None and _process.is_alive():
        if _window_id != window_id:
            raise RuntimeError("Preview targets another window; close and reopen it for this target")
        return
    show_viewer(window_id, allowed)


def show_viewer(window_id, allowed):
    global _process, _closed, _ready, _window_id
    with _lock:
        if stopped():
            raise InterruptedError("Preview stop is permanent; restart bridge locally")
        from . import windows_native as native
        native.enable_session_stop()
        native._stop_if_needed()
        if _process is not None and _process.is_alive():
            raise RuntimeError("Close the current preview before opening another")
        ctx = multiprocessing.get_context("spawn")
        _closed = ctx.Event()
        _ready = ctx.Event()
        native._stop_if_needed()  # A simultaneous stop must close the NEW event.
        errors = ctx.Queue()
        # A non-daemon preview may spawn disposable PrintWindow workers.
        candidate = ctx.Process(target=_run, args=(window_id, allowed, _closed, _ready, errors))
        candidate.start()
        # The stop watcher must not mistake a not-yet-started process for a dead
        # preview while Windows spawn is still starting it.
        _process = candidate
        _window_id = window_id
        deadline = time.monotonic() + 5
        try:
            while not _ready.wait(0.02):
                native._stop_if_needed()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Preview startup timed out")
            if _closed.is_set():
                try:
                    startup_error = errors.get(timeout=0.1)
                except queue.Empty:
                    raise InterruptedError("Preview closed during startup")
                raise RuntimeError("Preview startup failed: " + startup_error)
            native._stop_if_needed()
            if stopped():
                raise InterruptedError("Preview stopped during startup")
        except Exception:
            close_viewer()
            _process.terminate()
            _process.join(0.25)
            raise
    return {"visible": True, "window_id": window_id, "close_key": "Esc",
            "note": "Local live preview only; physical mouse uses the target window"}


def _run(window_id, allowed, closed, ready, errors):
    global _closed
    _closed = closed
    root = None
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
        from . import windows_native as native
        win = native.get_window(window_id, allowed)
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
        root.bind("<Escape>", lambda _: closed.set())
        root.protocol("WM_DELETE_WINDOW", closed.set)
        frames = queue.Queue(maxsize=1)

        def capture():
            while not closed.is_set():
                try:
                    current = native.get_window(window_id, allowed)
                    png, method, blank = native.capture_window(current)
                    frame = (png if not blank else None, current.title if not blank else "Không lấy được hình hợp lệ")
                except Exception as exc:
                    frame = (None, str(exc))
                try:
                    frames.put_nowait(frame)
                except queue.Full:
                    pass
                closed.wait(0.25)

        def tick():
            if (native.U.GetAsyncKeyState(0x1B) & 0x8000 or
                    native.U.GetAsyncKeyState(0x7B) & 0x8000):
                closed.set()
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
