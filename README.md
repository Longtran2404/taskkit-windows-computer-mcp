# TaskKit.vn Windows Computer Bridge MCP v0.4.8

[![Tests](https://github.com/Longtran2404/taskkit-windows-computer-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/Longtran2404/taskkit-windows-computer-mcp/actions/workflows/tests.yml)

**Developed by [TaskKit.vn](https://taskkit.vn) - Minh Long Tran.**

**Được phát triển bởi TaskKit.vn - Minh Long Tran.**

Local Windows MCP bridge for allowed windows. PNG screenshots are returned as MCP ImageContent to the connected AI client; the default workflow uses images in Codex chat. The optional separate live-preview window remains available, but does not open automatically.

## Input modes

- disabled: initial default; no physical input.
- foreground_confirm_each: legacy local confirmation for each action.
- foreground_session: owner-authorized session, with no per-action Yes dialogs. Escape/F12 cancels the current control task and stops further input. Read-only inspection and capture still work. Only a new owner-authorized task may explicitly call start_control_session; never automatically retry the cancelled task.

After the owner requests a new task or says to try again, call start_control_session, then inspect_windows and capture_window before input. Restart retires old preview/indicator/watcher workers and invalidates all earlier capture IDs. It refuses to restart while Esc/F12 is held. The cancelled operation is never replayed. Reopening the preview, inspecting windows or capturing does not rearm input.

Set the desired mode only in the local bridge_config.json. Example after owner authorizes a session:

```json
{"allow_processes":["notepad.exe","explorer.exe"],"mouse_control_mode":"foreground_session"}
```

Physical mouse/keyboard input shares the real desktop. Background PrintWindow capture can fail in GPU CAD/3D viewports. No credential access, binary patching, administrative rights or network listener is required.

## All applications

The owner can enable all applications without maintaining a process list:

```json
{"allow_processes":["*"],"mouse_control_mode":"foreground_session"}
```

Set this in the local JSON file selected by WIN10_BRIDGE_CONFIG. Codex's MCP environment must point to that file; restart/reconnect the running MCP once after a package or environment update. bridge_status reports application_scope=all_applications. Newly opened applications are included automatically. Existing process-name lists still work, and a new installation remains restricted with input disabled until the owner chooses otherwise.

This selects applications on the normal Windows desktop; it does not bypass Windows secure desktop, elevation/UIPI or unsupported GPU capture. ESC/F12 cancellation, explicit new-task restart, fresh single-use captures, foreground verification and pointer hit checks remain active for every application.

## Tools

bridge_status, start_control_session, inspect_windows, capture_window, capture_desktop, list_monitors, app_control, click_left, click_right, click_middle, scroll_mouse, mouse_action, type_text, press_key, inspect_controls, control_action, list_drives, open_directory, save_notepad_text, show_live_view, close_live_view, emergency_release.

### Unresponsive applications

PrintWindow and UI Automation run in disposable native worker processes with a five-second deadline. A blocked provider is stopped without terminating the application. Native calls do not block the MCP transport: bridge_status, window discovery and emergency stop remain available while another tool is waiting. bridge_status.native_operations reports active workers and the last timeout.

No capture ticket is issued on capture failure. A timed-out read sends no input. If an invocation, edit or focus request times out, its result is unknown: a separate observation gate pauses input while the session remains active. Call inspect_windows, then successfully capture_window of the current target/dialog; verify the image and continue the already authorized task. This needs no owner restart, approval question or start_control_session. Do not repeat the uncertain action automatically. Old capture tickets, failed/blank captures, desktop screenshots and observations already in flight before the failure cannot satisfy recovery. bridge_status.timeout_recovery reports the gate independently of session_stopped. ESC/F12, emergency_release and preview close still cancel the task; observation never clears that cancellation.

The input indicator appears on every monitor before authorized input or a live preview. Every overlay is created with topmost style, then periodically raised without activation; this fixes the Windows 10 case where the main-screen indicator stayed behind fullscreen while only the secondary-screen banner was visible. Each monitor retains its own border and centered banner without taking focus. bridge_status.control_indicator_displays reports actual monitor bounds and overlay handles. Capture exclusion of the layered indicator is best-effort; the fullscreen preview itself still requires successful capture exclusion.

Opt-in regression using only a disposable app with an intentionally blocked UIA provider:

```powershell
python scripts/live_timeout_test.py --run --out work/live-timeout-verification
```

Opt-in mutation timeout and recovery check (uses physical input only in its own disposable app):

```powershell
python scripts/live_recovery_test.py --run --out work/live-recovery-verification
```

v0.4.8 includes 59 unit tests and the real mutation-timeout -> inspection -> capture -> input check, without an owner restart or uncertain-action replay. Old tickets are invalidated atomically rather than compared by clock timestamps, including on Windows/Python 3.11. Existing checks cover the 22-tool stdio handshake, read timeout, 16 input/lifecycle cases and six desktop/dialog groups on two Windows 10 monitors. Desktop checks verify each indicator's physical monitor bounds and stacking above individual/panoramic fullscreen previews.

### Dialogs and fullscreen desktop

- inspect_windows includes enabled, owner_window_id and blocked_by_window_id. When a parent window is disabled by a modal dialog, inspect/capture the reported dialog and operate on its own window_id. Parent input is refused with a routing message; buttons are not automatically confirmed. The window preview follows the blocking dialog visually.
- list_monitors returns monitor IDs and virtual-desktop bounds, including negative origins.
- capture_desktop(monitor_id="all") returns one PNG for all screens. Pass a returned monitor ID to capture one screen. Metadata gives origin_x/origin_y, desktop size and image scales. No window input ticket is issued by a desktop screenshot.
- show_live_view(source="desktop", monitor_id="all", fullscreen=True) opens a panoramic fullscreen preview across all monitors. Select one monitor ID for single-screen fullscreen. Desktop viewing requires owner-authorized all-app scope.
- Call show_live_view again to switch source, monitor or fullscreen without stopping the task. The windowed preview has Fullscreen, Windowed and All screens buttons; F11 opens fullscreen from the focused preview. Use show_live_view(fullscreen=False, ...) to return without cancelling, or ESC/F12 to close and cancel. bridge_status.live_view reports the actual view state and frame readiness.
- Fullscreen preview is click-through, excluded from desktop capture to avoid recursion, and fills the selected display bounds. ESC/F12 or closing the preview cancels input; changing view modes does not. Windows secure desktop/UAC and protected capture surfaces remain OS limitations.

Desktop screenshots sent by capture_desktop go to the AI client. show_live_view alone displays frames locally. Inspect and capture the target application/dialog before input; existing foreground, hit-target and single-use capture checks still apply.

Owner-run desktop/dialog verification (temporarily uses its own fixture and all-app scope; captures stay in the local work folder):

```powershell
python scripts/live_desktop_test.py --run --out work/live-desktop-verification
```

v0.4.6 verification: 44 unit tests, 22-tool stdio handshake, 16 existing real input/lifecycle cases and five desktop/dialog scenarios. The latter were exercised on two Windows 10 monitors, including actual modal routing/closure, individual and panoramic fullscreen, switching modes without cancelling, capture-excluded/click-through preview and ESC cancellation.

- type_text supports Unicode and explicit replace_all in the focused editor.
- press_key supports bounded keys and chords, e.g. ctrl+s, ctrl+l, alt+n, enter, tab.
- inspect_controls returns bounded UI Automation controls, excluding passwords.
- control_action sets an edit value or invokes a uniquely identified button. Requires owner-armed foreground_session. Invoking a button is not proof that the requested effect occurred.
- open_directory opens an existing absolute local directory. Verify with Explorer window/state afterwards. Requires explorer.exe allowed.
- save_notepad_text writes and verifies a copy from the classic Notepad UIA editor buffer, refuses to overwrite differing data, and can open the copy. It does not mark the original editor as saved.

## Reliable original-window Save As

Inspect windows, identify the original editor, capture it, press ctrl+s. Inspect the resulting Save As window and capture it. Set File name control 1001 using control_action. Capture again and invoke Save control 1. Handle any confirmation only within the user's authorized file operation. Finally check BOTH the original editor title (no leading *) and the file contents on disk. Do not substitute a copy for saving the original editor.

Physical input verifies foreground and the target under mouse coordinates. UI Automation SetFocus provides a supported fallback when SetForegroundWindow alone fails. Fresh capture IDs expire and are single-use. Key/button releases run in finally blocks; drag waits are interruptible.

## Install

Python 3.11 or later with Tkinter is supported. The installer automatically uses the installed Python 3 interpreter; use -PythonVersion 3.11 or -PythonVersion 3.13 to select one explicitly. Run scripts/install_windows.ps1. Only run with -InstallCodex when the owner authorizes changing Codex registration. The installer preserves existing config. This repository contains only the Windows Computer Bridge package and its tests.

## Verification

v0.4.4 adds session restart regression tests and real same-process stop/restart checks. Read-only tools stay available after cancellation; actual input remains blocked until explicit new-session start. See CHANGELOG and the owner-run live test below for validated cases. After updating an already running Codex MCP process, reconnect/restart Codex once to load the new tool; subsequent session cancellations need no application restart.

23 unit tests pass on the local Windows machine (Python 3.13). Real stdio handshake lists 19 tools. Verified actual click, Vietnamese Unicode typing/replacement, ctrl+s and ctrl+home, original-window Save As (original title becomes iloveyou - Notepad without *), matching Desktop file, Explorer directory opening, and a Windows SendInput Escape pulse latching the stop and blocking subsequent typing/capture. Optional preview renders and closes cleanly with exit code 0. v0.4.3 adds 13 real stdio/input checks on a dedicated Windows fixture: left/right/middle clicks, double click, X1/X2, drag, timed hold, vertical/horizontal wheel, Ctrl+Shift drag, Vietnamese text and Esc stop. The Windows PowerShell 5.1 installer is verified with Python 3.13 and preserves the existing configuration byte-for-byte. CAD/3D GPU viewport behavior and other DPI layouts remain unverified; the indicator was verified on the two monitors of this setup. Built-in Computer Use screenshot capture timed out on this machine; Bridge PrintWindow supplied the verified images.

Apache-2.0; preserve LICENSE and NOTICE.

## Ownership and contributions

Repository owner and maintainer: **Longtran2404 (Minh Long Tran / TaskKit.vn)**. Direct write access is reserved for the owner; public visibility does not grant commit access. Others can read, fork, or propose pull requests, and the owner decides whether to accept them.

## Source and download

[GitHub repository](https://github.com/Longtran2404/taskkit-windows-computer-mcp) · [Download source ZIP](https://github.com/Longtran2404/taskkit-windows-computer-mcp/archive/refs/heads/main.zip)


## Owner-run live input verification

The live test uses its own disposable Tk window and temporarily allowlists python.exe. It occupies the physical pointer/keyboard and must only be run after owner authorization. It does not use production CAD/Revit models.

```powershell
python scripts/live_mouse_test.py --run --out work/live-input-verification
```

The runner records real window events, checks Unicode text in the editor, and confirms that a Windows Escape pulse latches the session stop. Generated logs, config and screenshots stay in the ignored work directory.

## Native initialization

TaskKit MCP initializes its Win32 backend on startup or the first native call. It does not depend on a Node REPL variable named sky. `bridge_status` exposes backend, initialization and requires_sky for diagnostics. A `sky is not defined` message belongs to an uninitialized external Computer Use REPL session; use the native MCP tools directly, or initialize that REPL using its documented bootstrap before calling sky.

## Separate mouse actions

Use click_left, click_right, click_middle or scroll_mouse for one clear action. The middle button tool presses the wheel button; scroll_mouse only rotates the wheel and sends no button press/release. Advanced mouse_action retains explicit button and action enums. Cleanup releases only input actually held by this bridge; it never sends unrelated right-button-up events after a left click.

## Visible control indicator

Before the first authorized input, the bridge shows a blue border fading inward on each monitor and a compact rounded banner: TaskKit MCP in use - ESC to cancel. The border is click-through and does not take focus. It remains visible during the input session and closes on Esc/F12, emergency stop or server exit. If it cannot start or exits unexpectedly, input is refused and the session stops. Live checks verify both monitor origins, preserved focus, 13 input cases and indicator closure on cancellation.


## App controls and visual cursor

app_control invokes supported UI Automation buttons or sets ValuePattern edit values without SetFocus, cursor movement or SendInput. A short blue cursor marker identifies visible app controls; it is visual, not a second Windows input device. Unsupported canvas/drag controls fail with no physical fallback. Each result reports observed pointer/focus changes; app providers may choose to activate their windows. Verified classic Notepad text update with pointer and foreground unchanged. General PDF/CAD dragging still uses the physical mouse or needs an application-specific API/isolated desktop.

The indicator uses the provided TaskKit transparent logo (original SVG and pre-rendered PNG included), a 24 px top offset, and static gradient/bevel/shadow depth. The resized logo is cached; there is no WebView or GPU 3D/animation dependency.

