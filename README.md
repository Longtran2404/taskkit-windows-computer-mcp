# TaskKit.vn Windows Computer Bridge MCP — review candidate 0.4.2.dev0

**Developed by [TaskKit.vn](https://taskkit.vn) — Minh Long Tran.**
**Được phát triển bởi TaskKit.vn — Minh Long Tran.**

Local stdio MCP bridge for explicitly allowed Windows windows, with window screenshots, physical mouse/keyboard and UI Automation. This candidate is prepared for owner review. The cloud checks exercise Linux, fake adapters and process isolation; they do not certify live Windows, CAD or GPU viewport compatibility. See [review evidence](docs/REVIEW_REPORT.md), [Windows checklist](docs/WINDOWS_MANUAL_CHECKLIST.md) and [hướng dẫn tiếng Việt](HUONG_DAN_VI.txt).

## Install on an owner-controlled Windows desktop

Use an interactive Windows 10/11 desktop with per-monitor DPI APIs and Python 3.11–3.13 including Tkinter and the `py.exe` launcher. Run from the extracted source directory without elevation:

```powershell
.\scripts\install_windows.ps1
# Choose another installed interpreter, if needed:
.\scripts\install_windows.ps1 -PythonVersion 3.13
```

The installer writes under LocalAppData and `%USERPROFILE%\Win10_ComputerBridge`, preserves existing configuration, and includes LICENSE/NOTICE. PowerShell installer execution has not been tested in this cloud. If local execution policy blocks it, resolve that according to the owner's policy; the bridge does not change policy or elevate itself.

Register with Codex only when the owner wants registration changed:

```powershell
.\scripts\install_windows.ps1 -PythonVersion 3.13 -InstallCodex
```

For a source checkout, an alternative is `py -3.13 -m venv .venv`, then `.\.venv\Scripts\python.exe -m pip install -e ".[test]"`. Start stdio with `.\.venv\Scripts\python.exe -m win10_bridge_mcp`. It does not open a network listener. Open Notepad first; the default allowlist is `notepad.exe`. New Notepad versions may not expose the classic editor automation ID `15`.

## Consent and stop

Edit only the local `bridge_config.json` to choose a mode:

| Mode | Input authorization |
| --- | --- |
| `disabled` (default) | Capture/inspection only; physical input and semantic mutations refused |
| `foreground_confirm_each` | Native local Yes/No dialog for each finite physical operation |
| `foreground_session` | Native local consent for up to **5 minutes**, bound to the configured allowlist/mode; prompts again after expiry |

```json
{"allow_processes":["notepad.exe"],"mouse_control_mode":"disabled"}
```

Changing config or supplying MCP arguments does not grant input consent. Every mutation tool defaults to `dry_run=true`. Status/capture/inspection do not arm input consent. Image transmission has separate local data-sharing consent. Esc/F12, closing the preview, `close_live_view` or `emergency_release` permanently stop capture, UIA and input for the process. Opening a preview cannot resume it. Restart locally to clear the latch, then approve a new input session locally. The key watcher polls; very brief pulses or changes of active Windows desktop may be missed. Use a deliberate held stop key or close the preview/bridge.

Physical `SendInput` occupies the real mouse and foreground focus. Keep hands off during the finite operation. Existing held keys/buttons cause refusal; cursor movement or loss of target identity/focus/geometry/DPI aborts. The bridge records its successful key/button downs and sends cleanup ups only for those. If a person presses the exact same key/button during an injected hold, asynchronous key-state APIs cannot distinguish ownership; this remains a limitation. Explicit emergency release sends broad best-effort ups and can affect owner-held input.

## Use and verify

1. Call `bridge_status`, then `inspect_windows`. Window IDs include PID, HWND and process creation time; IDs from older versions are incompatible.
2. Call `capture_window(window_id)`. Review the image before choosing coordinates. The PNG goes to the connected MCP/AI client and may contain sensitive data; the local preview instead keeps its frames local.
3. Request a dry run of the intended input using the returned `capture_id`. Coordinates are **physical pixels relative to the outer window**, including borders.
4. For an actual finite operation, enable the desired foreground mode locally, approve the local dialog and set `dry_run=false`. Capture again to verify the result.

Capture tokens expire after 90 seconds, are single-use for mutations, and bind identity, rectangle and DPI. Consent dialogs can outlive the token; capture again if it expires. Capture and UIA use disposable worker processes with a 3-second deadline including startup/result work. Timed out, crashed or late workers do not provide a token/result. Cancellation kills the worker, but a UIA mutation already dispatched to an application may still take effect: inspect UI/file state before retrying.

`PrintWindow` is best effort. Nonuniform pixels do **not** prove that a GPU/CAD viewport is correct, current or complete. Responses report method, status, timestamp, DPI, origin and uncertainty. Pixel dimensions and per-monitor awareness are checked. There is no full-desktop fallback or Windows Graphics Capture backend. Validate mixed-DPI/negative-monitor mapping manually before any CAD use. This bridge does not provide concurrent background physical input; use an application API or a separate Windows desktop/VM for that workflow.

## Choose screenshot scope explicitly

[`capture_screen`](docs/CAPTURE_MODES.md) supports `window`, `monitor`, `virtual_desktop` (all-monitor fullscreen) and `region`. Discover IDs/bounds with `inspect_capture_targets`; region coordinates are absolute physical pixels. Its default dry run sends no pixels. The owner enables eligible modes in local `capture_modes` (default `["window"]`), then approves a native data-sharing dialog. `capture_consent_mode=session` grants the exact scope for up to 5 minutes; `confirm_each` approves one capture. Existing `capture_window` also requires this separate screenshot consent. Neither grants input consent.

**Monitor/desktop/region screenshots can include other apps and sensitive contents. No automatic redaction is implemented.** Images are sent only to the configured MCP client after local scope consent. Broader modes never become a fallback for a failed window capture. Desktop observations never issue an input ticket; capture the chosen allowed app separately for input. All modes obey stop, deadline, bounds and a 12-million-pixel cap. The new desktop BitBlt backend and nominal DPI/scale mapping remain live-Windows-unverified; WGC is not implemented. See [examples and limits](docs/CAPTURE_MODES.md).

## App-only controls without bridge physical input

[`app_control_action`](docs/APP_ONLY.md) implements supported UIA Value, Invoke, SelectionItem and Scroll patterns in one selected window, without bridge cursor/input/focus APIs. Keep `mouse_control_mode=disabled`; locally enable `semantic_control_mode=app_confirm_each` or `app_session` (default `disabled`). App-session consent is separate, window-scoped and expires after 5 minutes. `inspect_controls` advertises available patterns; fresh capture and a unique non-password control are required.

Unsupported patterns return `unsupported_control`; no mouse/keyboard/focus/PostMessage fallback occurs. Native owner consent is interactive; the application/provider may itself change focus/UI in response to a semantic action. The window must be non-minimized, but need not be foreground. This is implemented and fake-tested code, with live Windows/provider/CAD/Blender support still unverified. See [feature details and examples](docs/APP_ONLY.md).

## Tools

`bridge_status`, `inspect_windows`, `capture_window`, `show_live_view`, `close_live_view`, `mouse_action`, `type_text`, `press_key`, `inspect_controls`, `control_action`, `save_notepad_text`, `list_drives`, `open_directory`, `emergency_release`, `app_control_action`, `capture_screen`, `inspect_capture_targets`.

- Mouse: move, click/double-click, bounded drag/hold, vertical/horizontal wheel; left/right/middle/X1/X2; Ctrl/Shift/Alt/Space modifiers.
- Text: bounded single-line literal Unicode, Vietnamese and UTF-16 emoji; `replace_all=true` explicitly performs Ctrl+A in the focused editor. Capture after clicking the intended editor first.
- Keys: bounded listed chords such as Ctrl+S and Ctrl+Home; system keys and Esc/F12 are reserved/excluded.
- UIA: bounded control inspection excluding password controls; identified edit `set_value` and button `invoke` need session consent. Each resolves fresh controls inside a deadline worker.
- `save_notepad_text`: copies the classic Notepad UIA buffer to an absolute `.txt` destination using exclusive creation. Verifies exact UTF-8 bytes and line endings, accepting an optional UTF-8 BOM; differing existing files are preserved. It does **not** mark the original editor as saved. File locality checks reject UNC/device/ADS/mapped-network destinations and check canonical local drive paths; filesystem reparse races are not a sandbox boundary.
- `open_directory`: requires session consent and explicitly allowlisted `explorer.exe`. Opening/invoking/input submission does not certify completion.

For original-window Save As, inspect/capture the current dialog, explicitly fill the intended destination and invoke Save; check both original editor title/state and file contents. Do not substitute a saved copy for a completed Save As.

## Local preview and diagnostics

Run `MO_MAN_HINH.cmd`, `scripts/open_preview.ps1` or `python -m win10_bridge_mcp.viewer` for optional local preview. Closing it stops that process. Frames may be unavailable when workers time out or the target is minimized/changed.

MCP runtime failures return `isError=true` with `structuredContent.error.code`, `message` and `effects_verified=false`; codes include `invalid_request`, `permission_denied`, `stop_or_intervention`, `native_timeout`, `file_exists`, `native_or_file_error`, `operation_failed`, `unsupported_control`. Framework argument-validation failures can use the MCP framework's own error text. An error after an input/UIA/file effect can mean partial completion; inspect before retrying. Stdio stdout is reserved for MCP messages.

```sh
python -m pytest -q
python scripts/smoke_test.py
python -m build
```

Smoke uses a temporary disabled config and never requests native consent or desktop input. CI defines Windows/Ubuntu × Python 3.11/3.13; Windows-labelled adapter tests remain simulations unless explicitly marked manual. The shell GitHub API proxy returned HTTP 403, then a read-only GitHub connector verified [all four baseline CI jobs](https://github.com/Longtran2404/taskkit-windows-computer-mcp/actions/runs/38553645474) succeeded for `92cfa9b`. The unpushed candidate has no remote CI run. Prior README live-Windows claims for v0.4.1 are historical owner reports and are not validation of this candidate.

Apache-2.0; preserve LICENSE and NOTICE. Repository owner/maintainer: **Longtran2404 (Minh Long Tran / TaskKit.vn)**. Public visibility does not grant write access. This review has not pushed, opened a PR, released or posted to a forum.

[Source repository](https://github.com/Longtran2404/taskkit-windows-computer-mcp) · [TaskKit.vn](https://taskkit.vn)
