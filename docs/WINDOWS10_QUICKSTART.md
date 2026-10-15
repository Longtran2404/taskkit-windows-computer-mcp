# Windows 10: an independent MCP workaround

Developed by [TaskKit.vn](https://taskkit.vn) - Minh Long Tran.

TaskKit Windows Computer Bridge MCP is free, Apache-2.0 software. It gives an MCP-capable AI client window screenshots, UI Automation and owner-authorized physical mouse/keyboard control through a separate Win32 backend. It does not depend on `@oai/sky`, patch OpenAI files, or require an administrator account.

This is an independent alternative workflow for people affected by built-in Computer Use capture failures. It is not an official OpenAI fix. Successful TaskKit capture does not establish the cause of the original failure. PrintWindow can also fail or return incomplete GPU/protected content; CapCut editor compatibility must be checked on the target machine.

## Install in Codex on Windows

1. Install Python 3.11 or later with Tkinter and the Windows `py` launcher. Have the Codex CLI available for MCP registration.
2. [Download the source ZIP](https://github.com/Longtran2404/taskkit-windows-computer-mcp/archive/refs/heads/main.zip), extract it and open PowerShell in the extracted folder. Review the source before running it.
3. After reviewing the downloaded source, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1 -InstallCodex`. The execution-policy setting applies only to that installer process; it does not change the saved Windows policy. On a managed machine, follow your organization's script policy.
4. Reconnect the MCP or restart Codex once. A new install allows only Notepad and has physical input disabled. Existing local configuration is preserved on update.
5. To authorize a control session, edit `%USERPROFILE%\Win10_ComputerBridge\bridge_config.json`:

```json
{"allow_processes":["notepad.exe"],"mouse_control_mode":"foreground_session"}
```

For all applications and desktop/multi-monitor screenshots, the owner can explicitly choose:

```json
{"allow_processes":["*"],"mouse_control_mode":"foreground_session"}
```

The default configuration is read for each tool call. If using a different file, set `WIN10_BRIDGE_CONFIG` in your MCP client's environment and reconnect. The optional `-InstallCodex` step registers the MCP under `win10-bridge`; installation alone does not register it in other clients.

## First test

Open a new blank Notepad yourself. Ask the AI:

> Use TaskKit MCP to inspect windows and capture this blank Notepad. If the image is valid, start the authorized control task, click in its editor, type “TaskKit capture test”, capture again and verify the text. End the control session when finished. Leave Notepad open.

Screenshots are sent to the connected AI service. Physical input uses the real mouse and keyboard. The blue border/banner appears on every monitor during control. Press physical ESC or F12 to cancel immediately. The AI must not restart the cancelled task; tell it to start a new task when you want to continue. A native timeout alone uses fresh inspection/capture recovery. `end_control_session` closes TaskKit overlays and releases input while leaving applications/documents open.

## If a window capture fails

Ask for `diagnose_capture(window_id=...)`. It tests the separate PrintWindow path with a bounded native worker. It reports captured, possibly blank, or failed, and returns a valid window image when available. A “captured” result still needs visual checking for missing GPU content.

Only with all-app scope and an explicit request, use `diagnose_capture(window_id=..., include_desktop=True, monitor_id="all")` for visible desktop observation. You may instead select an ID returned by `list_monitors`. Desktop images may include other applications. They do not bypass window capture checks, authorize physical input, clear a timeout recovery gate, or restart an ESC-cancelled/finished session. No input token is issued by diagnostics.

If the GPU viewport remains blank, report that limitation rather than sending blind coordinates. UAC/secure desktop and elevation restrictions remain Windows limitations. Do not replace OpenAI's signed helper to use this MCP.

## Update and feedback

Download the current source and rerun the installer, then reconnect the MCP once. There is no unattended auto-updater. Your existing configuration is preserved.

[Report a TaskKit issue](https://github.com/Longtran2404/taskkit-windows-computer-mcp/issues) with Windows version, TaskKit `bridge_status` version, application/version, steps and the short error. Review screenshots and logs for private information before sharing. Never include credentials or personal project content.
