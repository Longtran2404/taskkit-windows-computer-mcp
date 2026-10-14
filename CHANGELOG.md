# Changelog

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
