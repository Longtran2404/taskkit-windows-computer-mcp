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
- A successful input/invocation is not proof of a completed UI/file operation.
- Run python -m pytest -q and python scripts/smoke_test.py; document live Windows limitations.
