"""Owner-run onboarding/pause/revoke UI. Never called from an MCP tool."""
from .config import load_config
from .permissions import CAPABILITIES, eligible_capabilities


def enroll(store, cfg, apps, capabilities, days, *, owner_confirmed):
    """Local UI boundary, with explicit selections; no unattended default grant."""
    if owner_confirmed is not True:
        raise PermissionError("Explicit local owner consent required")
    if not apps or not set(apps) <= cfg["allowed"] or not capabilities or not set(capabilities) <= eligible_capabilities(cfg):
        raise PermissionError("Select apps/capabilities within local eligibility")
    import secrets
    from .permission_store import make_record
    secret = "tkcu_v1_" + secrets.token_urlsafe(32)
    record = make_record(apps, capabilities, secret, days)
    store.create(record)
    return record["profile_id"], secret


def main():
    from .owner_surface import desktop_surface_barrier
    with desktop_surface_barrier(owner=True):
        _owner_ui()


def _owner_ui():
    import tkinter as tk
    from tkinter import ttk, messagebox
    from .permission_store import WindowsGrantStore
    from .desktop_health import desktop_health
    cfg = load_config()
    store = WindowsGrantStore(create=True)
    root = tk.Tk()
    from .owner_surface import mark_owner_surface
    mark_owner_surface(root)
    root.title("TaskKit.vn — Quyền Computer Use của bridge")
    root.geometry("900x780")
    root.minsize(900, 550)
    canvas = tk.Canvas(root, highlightthickness=0)
    scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    canvas.configure(yscrollcommand=scrollbar.set)
    panel = ttk.Frame(canvas)
    panel_window = canvas.create_window((0, 0), window=panel, anchor="nw")
    panel.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(panel_window, width=event.width))
    health = desktop_health()
    ttk.Label(panel, text="Chủ máy chọn phạm vi một lần. Cài/kết nối MCP không tự cấp quyền.", wraplength=850).pack(pady=8)
    ttk.Label(panel, text=f"Desktop: {health.get('thread_desktop')} / input: {health.get('input_desktop')} — {health['status']}", wraplength=850).pack()
    ttk.Label(panel, text="Grant xác thực profile riêng bằng credential; không phải quyền/tài khoản ChatGPT.\n"
              "Mọi cửa sổ hiện tại/tương lai của app đã chọn nằm trong scope. Tiến trình có cùng credential có thể dùng profile.\n"
              "Mouse/focus thật bị chiếm nếu chọn physical input. Host vẫn cần xử lý xác nhận hành động nhạy cảm.", wraplength=850).pack(pady=8)
    ttk.Label(panel, text="App/physical/file actions cần capture_window để có token mới. File save còn cần uia_read.\n"
              "Bạn phải tự chọn các quyền đọc/chia sẻ dữ liệu này; bridge không tự thêm.", wraplength=850).pack(pady=4)
    apps = {}
    for exe in sorted(cfg["allowed"]):
        apps[exe] = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text=exe, variable=apps[exe]).pack(anchor="w", padx=20)
    caps = {}
    for cap in sorted(eligible_capabilities(cfg)):
        caps[cap] = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text=CAPABILITIES[cap], variable=caps[cap]).pack(anchor="w", padx=20)
    days = tk.StringVar(value="7")
    ttk.Label(panel, text="Hết hạn sau (ngày):").pack()
    ttk.Combobox(panel, state="readonly", values=("1", "7", "30"), textvariable=days, width=10).pack()
    confirmed = tk.BooleanVar(value=False)
    ttk.Checkbutton(panel, text="Tôi là chủ máy và đồng ý phạm vi đã chọn; hiểu dữ liệu có thể được gửi cho AI host.", variable=confirmed).pack(pady=8)

    def create():
        try:
            if not health["usable_interactive_context"]:
                raise PermissionError("Chạy onboarding từ input desktop của chủ máy; không chuyển/bỏ sandbox")
            profile_id, secret = enroll(store, cfg, [a for a, v in apps.items() if v.get()],
                                       [c for c, v in caps.items() if v.get()], int(days.get()), owner_confirmed=confirmed.get())
            dialog = tk.Toplevel(root)
            mark_owner_surface(dialog)
            dialog.title("Credential profile — chỉ hiển thị local một lần")
            ttk.Label(dialog, text="Cấu hình secret trong secure environment của đúng AI host. Không gửi vào chat/log/GitHub.\n"
                      "TASKKIT_CLIENT_ID:").pack(padx=12, pady=8)
            identity = ttk.Entry(dialog, width=60)
            identity.insert(0, profile_id); identity.configure(state="readonly"); identity.pack()
            ttk.Label(dialog, text="TASKKIT_CLIENT_SECRET (đóng hộp này sẽ mất bản plaintext):").pack(pady=8)
            credential = ttk.Entry(dialog, width=70, show="*")
            credential.insert(0, secret); credential.pack(padx=12)
            reveal = tk.BooleanVar(value=False)
            ttk.Checkbutton(dialog, text="Hiện credential local", variable=reveal,
                            command=lambda: credential.configure(show="" if reveal.get() else "*")).pack()
            ttk.Label(dialog, text="Grant không tự bật. Đặt authorization_mode=persistent local và truyền credential qua env.\n"
                      "Không ghi secret vào MCP args/source hoặc public config; không có MCP grant/resume tool.", wraplength=600).pack(padx=12, pady=12)
            confirmed.set(False)
        except Exception as exc:
            messagebox.showerror("Chưa cấp quyền", str(exc), parent=root)
    ttk.Button(root, text="Cấp grant mới theo lựa chọn", command=create).pack(pady=4)

    profile = tk.StringVar()
    ttk.Label(panel, text="Profile ID để Pause / Resume / Revoke (không phải secret):").pack(pady=6)
    ttk.Entry(panel, textvariable=profile, width=50).pack()
    def change(state):
        if not messagebox.askyesno("Owner quản lý quyền", f"{state} profile {profile.get()}?\nResume cần reconnect; revoked không thể resume.", parent=root):
            return
        try:
            store.set_state(profile.get(), state)
            messagebox.showinfo("Đã cập nhật", "Kết nối hiện tại bị vô hiệu; reconnect chỉ khi grant active và credential hợp lệ.", parent=root)
        except Exception as exc:
            messagebox.showerror("Không cập nhật", str(exc), parent=root)
    buttons = ttk.Frame(panel); buttons.pack(pady=8)
    for label, state in (("Pause", "paused"), ("Resume / recover crash", "active"), ("Revoke", "revoked")):
        ttk.Button(buttons, text=label, command=lambda s=state: change(s)).pack(side="left", padx=4)
    root.mainloop()
