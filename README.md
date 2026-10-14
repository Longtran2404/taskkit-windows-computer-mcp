# TaskKit.vn Windows Computer Bridge MCP v0.4.1

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

bridge_status, inspect_windows, capture_window, mouse_action, type_text, press_key, inspect_controls, control_action, list_drives, open_directory, save_notepad_text, show_live_view, close_live_view, emergency_release.

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

Python 3.11 with Tkinter is required by the preserved installer. Run scripts/install_windows.ps1. Only run with -InstallCodex when the owner authorizes changing Codex registration. The installer preserves existing config. This repository contains only the Windows Computer Bridge package and its tests.

## Verification

16 unit tests pass on the local Windows machine (Python 3.13). Real stdio handshake lists 14 tools. Verified actual click, Vietnamese Unicode typing/replacement, ctrl+s and ctrl+home, original-window Save As (original title becomes iloveyou - Notepad without *), matching Desktop file, Explorer directory opening, and a Windows SendInput Escape pulse latching the stop and blocking subsequent typing/capture. Optional preview renders and closes cleanly with exit code 0. All CAD/3D gestures, GPU rendering and Python 3.11 installer execution remain unverified. Built-in Computer Use screenshot capture timed out on this machine; Bridge PrintWindow supplied the verified images.

Apache-2.0; preserve LICENSE and NOTICE.

## Ownership and contributions

Repository owner and maintainer: **Longtran2404 (Minh Long Tran / TaskKit.vn)**. Direct write access is reserved for the owner; public visibility does not grant commit access. Others can read, fork, or propose pull requests, and the owner decides whether to accept them.

## Source and download

[GitHub repository](https://github.com/Longtran2404/taskkit-windows-computer-mcp) · [Download source ZIP](https://github.com/Longtran2404/taskkit-windows-computer-mcp/archive/refs/heads/main.zip)

