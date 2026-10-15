# Changelog

## 0.4.9 - 2026-10-16

Developed by TaskKit.vn - Minh Long Tran.

- Add end_control_session for completed computer work or handoff. Stop before waiting for the input mutex, release held input, invalidate capture tickets and verify preview/indicator threads exit. Keep applications/documents open and MCP read-only inspection connected. Repeated finish calls are safe.
- Send the finish policy through MCP initialization instructions and tool descriptions: call the finish tool before final response, waiting for the owner or leaving desktop work. Do not infer completion from a silent client or replay cancelled operations.
- Expose last completion/handoff reason. A new owner-authorized task resets completion state through start_control_session; timeout recovery and ESC/F12 cancellation retain their existing contracts.
- 66 unit tests, 23-tool handshake and a real same-process fixture verify interrupted hold/release, closed overlays, stale-ticket rejection, blocked post-finish input, available read-only capture, repeated cleanup, application preservation and new-task handoff.

## 0.4.8 - 2026-10-15

Developed by TaskKit.vn - Minh Long Tran.

- Separate uncertain native timeout/worker failure from owner cancellation. Keep the authorized session active; require inspect_windows followed by a successful fresh capture_window before continuing input. No owner restart question or start_control_session is needed solely for timeout.
- Reject pre-recovery capture tickets and in-flight/blank/failed/desktop observations. Never replay the uncertain native operation. Preserve ESC/F12, emergency release and preview-close stop latches; read-only recovery cannot clear owner cancellation.
- Expose timeout_recovery independently of session_stopped and add recovery instructions to tool descriptions. Explicitly owner-authorized new tasks still invalidate old tickets and reset recovery history.
- Reproduce the main-monitor indicator losing topmost style behind fullscreen while the secondary banner remained visible. Create every indicator with WS_EX_TOPMOST immediately; verify both styles and stacking again after application input, plus a real two-screen banner image.
- Add unit regressions for recovery order, stale tickets, failed/in-flight observations, worker failure and preserved emergency stop. Add an opt-in real UIA mutation-timeout -> inspection -> capture -> physical input fixture, with no owner restart or action replay.
- Invalidate old tickets atomically when observation succeeds, independent of Windows/Python clock resolution. Include a frozen-clock regression.
- 59 unit tests and the real mutation recovery fixture pass locally; preserve the existing stdio, input/lifecycle and two-monitor checks.

## 0.4.7 - 2026-10-15

Developed by TaskKit.vn - Minh Long Tran.

- Isolate blocking PrintWindow and UI Automation operations in disposable worker processes with a five-second deadline. Kill/reap the actual interpreter worker rather than only the Windows virtual-environment redirector; preserve the target application.
- Dispatch native MCP tools off the transport event loop so status, discovery and emergency stop remain responsive during another blocked provider call. Keep capture/input/session ticket issuance serialized.
- Expose active native operations and the last failure. Read timeouts send no input; capture failure issues no ticket. Timed-out mutations latch stop and report an unknown result, with no automatic retry or replay; ESC/F12 cancels the in-progress mutation worker.
- Show the input indicator before live preview, with a centered banner on every monitor. Refresh overlay stacking without activation so later fullscreen previews cannot hide one monitor's border/banner. Expose actual per-monitor overlay bounds in status.
- Add timeout, worker cleanup, transport responsiveness and no-ticket/no-replay regressions. Add an opt-in real hung-provider fixture and extend the two-monitor fullscreen check to verify both overlay geometries and stacking.
- Local validation: 51 unit tests, 22-tool stdio handshake, 16 real input/lifecycle cases, six desktop/dialog groups and real provider timeout recovery on Windows 10.

## 0.4.6 - 2026-10-15

Developed by TaskKit.vn - Minh Long Tran.

- Identify disabled parent windows and their blocking dialogs, including small/untitled owned windows. Refuse input to disabled parents and direct inspection to the dialog; window preview follows the active blocking dialog.
- Add list_monitors and capture_desktop for one screen or all monitors in a single image, with negative-origin coordinates and scale metadata. Desktop capture requires all-app scope and issues no window input ticket.
- Add desktop/window source selection, single/multi-monitor fullscreen, F11/windowed controls and mode changes without cancelling the session to show_live_view.
- Fullscreen preview is click-through and excluded from desktop capture. Exclude internal preview/indicator windows from application discovery; expose actual preview geometry and frame readiness in bridge_status.
- Preserve ESC/F12 cancellation and explicit new-task restart, including fullscreen mode.
- 44 unit tests, 22-tool stdio handshake and 16 existing real input/lifecycle cases pass. Verify five additional live desktop/dialog scenarios on a two-monitor Windows 10 setup, including preview capture exclusion and physical input through fullscreen preview.

## 0.4.5 - 2026-10-15

Developed by TaskKit.vn - Minh Long Tran.

- Add explicit owner-selected allow_processes=["*"] to support all identifiable applications, including applications opened later, without per-executable configuration.
- Apply the same scope to native window discovery, capture, input, UI Automation, preview and Explorer directory opening.
- Expose application_scope in bridge_status. Preserve selected-app mode and disabled-input defaults for new installations.
- Keep emergency cancellation, explicit new-task restart, fresh capture tickets, foreground and hit checks unchanged.
- Add wildcard validation, native enumeration and configuration regression tests; add --all-apps to the real Windows input/lifecycle fixture.
- 37 unit tests and 16 real input/lifecycle cases pass locally in all-application mode. A new application opened after the stdio server starts is discovered and captured with input still disabled.

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
