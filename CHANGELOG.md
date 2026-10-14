# Changelog

## 0.4.4 - 2026-10-15

Developed by TaskKit.vn - Minh Long Tran.

- Fix inspect_windows, inspect_controls and capture_window failing after Esc/F12 cancellation. These read-only tools do not rearm input.
- Add start_control_session for a new owner-authorized task, with no per-action dialog. Never automatically retry or replay a cancelled task.
- Retire previous preview, indicator and emergency watcher before starting the new session. Old watcher events stay stopped; held Esc/F12 refuses restart.
- Invalidate all screenshot tickets at restart; require a fresh capture before input.
- Run the optional preview on a dedicated GUI thread, with Tk objects cleaned up on that thread, avoiding a stalled Windows spawned interpreter and cross-thread Tcl cleanup.
- Add unit regressions and live same-process tests for Esc cancellation, blocked input, explicit restart, stale capture rejection, F12 restart and preview-close restart.
- 30 unit tests, 20-tool stdio handshake and 16 real Windows input/lifecycle cases pass locally. Preview startup and clean shutdown also pass in the stdio fixture.

## 0.4.3 - 2026-10-14

Developed by TaskKit.vn - Minh Long Tran.

- Fix unrelated right/middle/X button-up events after every input operation. Foxit could open a context menu after a left click because the old cleanup released all buttons.
- Track only buttons and virtual keys pressed by the bridge. Cleanup releases only held input, including after an interrupted drag.
- Separate click_left, click_right, click_middle and scroll_mouse tools. Keep mouse_action for double click, drag, hold and X buttons; expose enum schemas.
- Automatic blue monitor borders with an inward alpha fade and rounded banner: TaskKit MCP in use - ESC to cancel. Click-through, no focus takeover; Esc/F12 closes the indicator and stops the session. Live verification covers both monitor origins and the cancellation lifecycle.
- Add app_control for supported UIA controls by unique ID or exact name, without physical-input fallback. Verify Notepad value, unchanged pointer and focus; visual cursor is a marker, not an independent input device.
- Package the official TaskKit SVG/PNG logo; lower the banner by 16 px and add lightweight static surface depth with cached logo rendering.
- 23 unit tests and 19-tool MCP handshake pass locally. Verify 13 real input cases and reject unrelated button events in the live fixture.

## 0.4.2 - 2026-10-14

Developed by TaskKit.vn - Minh Long Tran.

- Official standalone v0.4.2 release on the main branch.
- Installer supports Python 3.11+ and automatically selects installed Python 3.
- Explicit PythonVersion, InstallDir and ConfigDir options; preserve existing config and back up prior source.
- Package includes LICENSE and NOTICE and reports its version through bridge_status.
- Add owner-run event-verified Windows input fixture and runner with explicit --run opt-in.
- 16 unit tests and MCP protocol checks pass locally; 13 real input cases pass on the installed v0.4.2 package.
- Verify installer under Windows PowerShell 5.1 with Python 3.13; existing config hash unchanged.
- CI checks installation on Windows Python 3.11/3.13 in addition to unit and stdio tests on Windows/Linux.

Live coverage: left/right/middle click, double click, X1/X2, drag, timed hold, vertical/horizontal scrolling, Ctrl+Shift drag, Vietnamese Unicode input and latched Escape stop.

CAD/3D GPU viewports and multiple-monitor/DPI layouts require separate project-specific validation.

## 0.4.1

Initial standalone TaskKit.vn publication with 14 MCP tools, native window capture, Unicode keyboard, UI Automation, directory opening, original-editor Save As verification and owner-authorized sessions.
