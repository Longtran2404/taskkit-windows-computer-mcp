"""Local live window preview. Closing it latches a stop until reopened."""
from __future__ import annotations

from io import BytesIO
import queue
import threading
import multiprocessing

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
        raise InterruptedError("Preview was closed; reopen with show_live_view to resume")
    if _process is not None and _process.is_alive():
        if _window_id != window_id:
            raise RuntimeError("Preview targets another window; close and reopen it for this target")
        return
    show_viewer(window_id, allowed)


def show_viewer(window_id, allowed):
    global _process, _closed, _ready, _window_id
    with _lock:
        if _process is not None and _process.is_alive():
            raise RuntimeError("Close the current preview before opening another")
        STOP.clear()
        ctx = multiprocessing.get_context("spawn")
        _closed = ctx.Event()
        _ready = ctx.Event()
        errors = ctx.Queue()
        _process = ctx.Process(target=_run, args=(window_id, allowed, _closed, _ready, errors), daemon=True)
        _process.start()
        _window_id = window_id
        if not _ready.wait(5):
            close_viewer()
            raise RuntimeError("Preview startup timed out")
        if _closed.is_set():
            _process.join(1)
            raise RuntimeError(errors.get(timeout=1) if not errors.empty() else "Preview closed during startup")
    return {"visible": True, "window_id": window_id, "close_key": "Esc",
            "note": "Local live preview only; physical mouse uses the target window"}


def _run(window_id, allowed, closed, ready, errors):
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
            if native.U.GetAsyncKeyState(0x1B) & 0x8000:
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
