# TaskKit.vn Windows Computer Bridge MCP

- Maintain this standalone Windows MCP package; no Revit dependency is required.
- Preserve Apache-2.0, NOTICE, TaskKit.vn branding and developer attribution.
- Never commit credentials, local configs, screenshots, user documents or generated dependencies.
- Keep physical input disabled by default. foreground_session requires owner authorization.
- Local owners can explicitly choose allow_processes=["*"] for all applications. Preserve that choice on updates; keep the default installer restricted and input disabled.
- Esc/F12 must latch a stop for the cancelled task; never automatically resume or replay it. A new owner-authorized task may explicitly call start_control_session after retiring old workers and invalidating all capture tickets.
- Verify foreground window, fresh capture tokens and pointer hit target before input.
- Desktop capture/preview requires all-app scope and does not issue window input tickets. Keep preview capture-excluded and fullscreen click-through.
- Inspect and target a blocking dialog explicitly; never auto-confirm it or send input to its disabled parent.
- Keep native capture/UIA calls bounded and isolated. Reap blocked workers without terminating the application; never replay uncertain mutations. Keep MCP status/emergency stop responsive and both monitor indicators above fullscreen previews without activation.
- A native timeout is recoverable within the existing authorized task, not owner cancellation. Require inspect_windows followed by a successful fresh capture_window; reject old tickets and never clear Esc/F12. Do not ask for owner restart solely because a worker timed out.
- AI clients must call end_control_session after final computer verification, before their final response, waiting for the owner, or leaving desktop work. Close all TaskKit overlays, release held input and invalidate tickets while keeping applications/documents open and the MCP connection available for reads. Do not automatically replay input or rearm after finishing.
- A successful input/invocation is not proof of a completed UI/file operation.
- Run python -m pytest -q and python scripts/smoke_test.py; document live Windows limitations.
