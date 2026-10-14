# TaskKit.vn Windows Computer Bridge MCP

- Maintain this standalone Windows MCP package; no Revit dependency is required.
- Preserve Apache-2.0, NOTICE, TaskKit.vn branding and developer attribution.
- Never commit credentials, local configs, screenshots, user documents or generated dependencies.
- Keep physical input disabled by default. foreground_session requires owner authorization.
- Esc/F12 must latch a stop for the cancelled task; never automatically resume or replay it. A new owner-authorized task may explicitly call start_control_session after retiring old workers and invalidating all capture tickets.
- Verify foreground window, fresh capture tokens and pointer hit target before input.
- A successful input/invocation is not proof of a completed UI/file operation.
- Run python -m pytest -q and python scripts/smoke_test.py; document live Windows limitations.
