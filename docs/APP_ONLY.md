# App-only semantic controls — implemented candidate feature

`app_control_action` implements app-scoped UI Automation **SetValue, Invoke, SelectionItem.Select and Scroll**. It does not use physical input or request foreground focus. This is implemented code with fake-adapter regression, not a promise of live Windows/app compatibility.

| Path | Intended use | Bridge physical input/focus | Permission |
| --- | --- | --- | --- |
| `mouse_action`, `type_text`, `press_key` | Coordinates and keyboard in the foreground | Uses real cursor/SendInput/focus | `mouse_control_mode` + local owner consent |
| `control_action` | Existing foreground UIA SetValue/Invoke | Requests foreground; UIA operation | `foreground_session` + local owner consent |
| `app_control_action` | Supported control patterns in the selected window | No SetCursorPos/SendInput/SetForegroundWindow/SetFocus or PostMessage fallback | Separate `semantic_control_mode` + local owner consent |

The local consent dialog itself requires owner interaction. An application/provider can choose to bring its own window forward, open a dialog or cause its own cursor/focus side effects as a result of Invoke/Selection. The bridge does not force or fake background behavior when the provider requires focus. Keep physical mode disabled for app-only use:

```json
{
  "allow_processes": ["notepad.exe"],
  "mouse_control_mode": "disabled",
  "semantic_control_mode": "app_session"
}
```

`semantic_control_mode` defaults to `disabled`; existing configs keep that default. `app_confirm_each` asks locally for each finite semantic operation and shows its material value/scroll payload. `app_session` grants SetValue/Invoke/Select/Scroll in **one selected window** for up to 5 minutes. Changing the window, allowlist or semantic mode, or expiry, requires new local consent. It never grants physical input permission. Esc/F12 and preview close permanently stop both paths; there is no MCP arm/resume tool.

## Workflow

1. Inspect allowed windows and choose the current ID. Capture it with the separate local data-sharing consent and visually verify the target. Screenshot permission does not arm app-only mutation consent. See [capture modes](CAPTURE_MODES.md).
2. `inspect_controls(window_id)` lists non-password controls from the selected process with `app_only_patterns`. This advertises provider capabilities; each execution resolves them again.
3. Use a unique, nonempty `automation_id`, the fresh one-use `capture_id` and `dry_run=true` to review the request. Dry run does not mutate, consume the token or arm consent; it reports `pattern_verified=false`.
4. Enable the semantic mode locally. Run with `dry_run=false`, approve the local dialog and verify resulting app/UI state.

Examples of tool arguments (replace IDs with inspected values):

```json
{"window_id":"...","capture_id":"...","automation_id":"15","action":"set_value","value":"Tiếng Việt 😀","dry_run":false}
```

```json
{"window_id":"...","capture_id":"...","automation_id":"button-id","action":"invoke","dry_run":false}
```

```json
{"window_id":"...","capture_id":"...","automation_id":"item-id","action":"select","dry_run":false}
```

```json
{"window_id":"...","capture_id":"...","automation_id":"scroll-container-id","action":"scroll","horizontal":"none","vertical":"small_increment","dry_run":false}
```

Scroll choices are `none`, `small_decrement`, `small_increment`, `large_decrement`, `large_increment`; at least one axis must scroll. Scroll units are semantic provider units; they are not wheel ticks or viewport pixels. SelectionItem.Select replaces the container's selection according to its provider semantics. Value requires writable ValuePattern; literal NUL and invalid UTF-16 strings are refused, while multiline values are allowed. Invoke requests an action and does not certify its downstream completion.

## Guards and unsupported cases

Each action runs in the same disposable 3-second UIA worker as other UIA operations. Parent guards and child guards enforce permanent stop and consent deadline; the child reads the current local semantic mode/allowlist immediately before each effect. Window identity, rectangle and DPI must match the capture. The target stays visible/non-minimized under current window/capture policy; it can be behind another window and need not be foreground.

The control must be unique, enabled, non-password, in the selected process and within the captured outer window. Its current UIA root must match the selected HWND/PID and freshly resolved root. A bounded RawViewWalker ancestry check (up to 64 levels) confirms it remains under that root before/after effects. Reparented/foreign/ambiguous/off-window controls are refused. Password controls are omitted before reading name/pattern/value; password-state changes are rechecked before effects and Value reads.

Missing/unusable patterns, read-only Value and unsupported scroll axes return structured `unsupported_control` with `isError=true`. Scope/consent failures and stop use their respective error codes. There is **no silent fallback** to mouse, keyboard, focus, PostMessage, elevation or another target. App-only execution does not consume physical consent; it consumes the screenshot token once before dispatch.

Value reports `value_matches`; Select reports `selected`; Scroll reports before/after percentages and whether they changed. An unchanged percentage can mean a boundary. Invoke and downstream effects remain unverified. A provider may complete an already-dispatched mutation after worker cancellation; verify state before retrying. UIA property/ancestry checks and the provider call cannot be atomic against every app tree change.

## What is tested and what is proposed

Implemented and fake-tested: all four pattern paths; no calls to physical/focus APIs; separate default-disabled consent; target window grants; current root/ancestry/PID/bounds/password; read-only/disabled/missing-pattern refusal; state/percentage readback; stop/deadline/config change at pattern boundaries; structured errors and indeterminate post-effect failure.

Not live-validated: Windows COM/providers, actual occluded app support, Tkinter/consent behavior or CAD/Blender/GPU viewport operations. Real app APIs or a separate Windows desktop remain options for viewport-independent work; no CAD/Blender API integration or universal background mouse emulation is implemented here. Follow [Windows manual checks](WINDOWS_MANUAL_CHECKLIST.md).

Primary API references: [UIA patterns overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-controlpatternsoverview), [IUIAutomationScrollPattern](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nn-uiautomationclient-iuiautomationscrollpattern), [ScrollAmount](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationcore/ne-uiautomationcore-scrollamount). Provider pattern availability is application-specific and can change dynamically.
# Persistent owner profile option

The window-scoped dialogs below describe default legacy authorization. The optional [owner profile](OWNER_PERMISSIONS.md) reuses an explicitly enrolled app/capability scope across windows and clean connections without repeated dialogs; pattern/identity/geometry/stop guards remain. This permissions upgrade has not been verified with a live Windows provider.
