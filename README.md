# TaskKit.vn Windows Computer Bridge MCP v0.4.3

[![Tests](https://github.com/Longtran2404/taskkit-windows-computer-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/Longtran2404/taskkit-windows-computer-mcp/actions/workflows/tests.yml)

**Developed by [TaskKit.vn](https://taskkit.vn) - Minh Long Tran.**

**Được phát triển bởi TaskKit.vn - Minh Long Tran.**

Local Windows MCP bridge for allowed windows. PNG screenshots are returned as MCP ImageContent to the connected AI client; the default workflow uses images in Codex chat. The optional separate live-preview window remains available, but does not open automatically.

## Input modes

- disabled: initial default; no physical input.
- foreground_confirm_each: legacy local confirmation for each action.
- foreground_session: owner-authorized session, with no per-action Yes dialogs. Escape/F12 permanently stops the process session, including further screenshot capture. No remote resume tool exists. A new explicitly authorized server session is required to resume.

Set the desired mode only in the local bridge_config.json. Example after owner authorizes a session:

```json
{"allow_processes":["notepad.exe","explorer.exe"],"mouse_control_mode":"foreground_session"}
```

Physical mouse/keyboard input shares the real desktop. Background PrintWindow capture can fail in GPU CAD/3D viewports. No credential access, binary patching, administrative rights or network listener is required.

## Tools

bridge_status, inspect_windows, capture_window, app_control, click_left, click_right, click_middle, scroll_mouse, mouse_action, type_text, press_key, inspect_controls, control_action, list_drives, open_directory, save_notepad_text, show_live_view, close_live_view, emergency_release.

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

