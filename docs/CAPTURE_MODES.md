# Explicit capture modes and data-sharing consent

Implemented candidate tools: `inspect_capture_targets` and `capture_screen`. Existing `capture_window` uses the same local data-sharing consent for its window-only path. Neither path grants physical input or app-only mutation consent.

| Mode | Target and coordinates | Backend | Input token |
| --- | --- | --- | --- |
| `window` | Selected allowlisted `window_id`; outer-window physical pixels | PrintWindow | Window-scoped token, still requires separate input consent |
| `monitor` | Exact `monitor_id` from discovery, whole monitor | GDI BitBlt | None |
| `virtual_desktop` | Bounding rectangle of all active monitors; may include gaps and negative origins | GDI BitBlt | None |
| `region` | Explicit `left`, `top`, `width`, `height` in absolute physical desktop pixels | GDI BitBlt | None |

“App capture” means one selected window. “Fullscreen” can mean one monitor or the entire virtual desktop; select the corresponding explicit mode. Capture mode/backend never changes automatically after failure. Desktop modes are deliberate separate requests, not a fallback for failed PrintWindow.

## Local setup and scope

Default `capture_modes` is `["window"]`; monitor/virtual-desktop/region are disabled. The owner may enable needed modes locally:

```json
{
  "allow_processes": ["notepad.exe"],
  "mouse_control_mode": "disabled",
  "semantic_control_mode": "disabled",
  "capture_modes": ["window", "monitor", "region"],
  "capture_consent_mode": "session"
}
```

The configuration is eligibility, not data-sharing approval. Before transmitting an image, a native local dialog identifies the mode/scope and connected MCP/AI client. `capture_consent_mode=confirm_each` asks for each finite capture. `session` asks for repeated capture of exactly that scope for at most 5 minutes; changed mode/target region/desktop layout/enabled mode list, expiry or relevant config changes require new approval. Window grants cover the selected process/window identity; changed window geometry still requires a fresh, stable capture.

Use `capture_modes=[]` to disable MCP image transmission. MCP cannot change these settings, approve the local dialog or clear stop. Closing preview/Esc/F12/emergency stop blocks all modes permanently for the process. Status and target discovery transfer geometry only and never arm screenshot consent. Local preview remains local and does not use the MCP data-sharing grant.

**Desktop/monitor/region images can include other applications, private documents or visible secrets even if those apps are not allowlisted for input. No automatic redaction is implemented.** Approving one target does not approve another. Contents within a granted scope can change during its five-minute period. This feature request does not itself send any user screenshot in the Linux review environment; all image tests are synthetic.

## AI selection workflow

Call `inspect_capture_targets` to read allowed window IDs, monitor IDs, absolute rectangles, scale/DPI metadata, virtual bounds, enabled modes and max pixels. Choose a permitted mode and review its dry run (the default). Example arguments:

```json
{"mode":"window","window_id":"...","dry_run":true}
```

```json
{"mode":"monitor","monitor_id":"monitor:...","dry_run":true}
```

```json
{"mode":"virtual_desktop","dry_run":true}
```

```json
{"mode":"region","left":-1200,"top":100,"width":800,"height":600,"dry_run":true}
```

Set `dry_run=false` to request the capture after local enablement and native owner consent. A dry run transfers no pixels, prompts no consent and grants no input. If the owner has enabled only window mode, the AI receives an explicit permission error for desktop/region requests.

Region must have positive dimensions, fit within virtual desktop bounds and remain within Win32 coordinate range. Maximum image area is **12,000,000 pixels** for every mode. Large multi-4K desktops can exceed the cap; select an explicit monitor/region. There is no silent downscale, clamp or broader capture. Gaps in monitor arrangements may appear blank. Capture can fail rather than guess an unsupported layout.

## Mapping, metadata and deadlines

Responses include explicit mode, rectangle/origin, PNG width/height, backend, timestamp, elapsed time and uncertainty. Image-relative coordinates plus origin map to absolute physical desktop pixels. Window responses retain their original window-relative ticket mapping. Desktop `capture_id` is null, with `input_authorization=false`; its random `observation_id` is not in the capture registry and cannot authorize input. To mutate an app after viewing desktop pixels, inspect and capture that allowed window separately and obtain its own mutation consent.

Native mapping requires per-monitor-aware thread context and MM_TEXT desktop/memory DCs. Active monitor rect union is cross-checked against `GetSystemMetricsForDpi(...,96)`. Display layout/scale snapshots are checked during waits and after PNG encoding. DIB drawing is synchronized with checked `GdiFlush` before reading pixels. Every native worker has a 3-second deadline with bounded terminate/kill cleanup; late/crashed/changed-layout results are discarded. Failed cleanup latches stop.

Window DPI comes from GetDpiForWindow. Desktop metadata uses GetScaleFactorForMonitor and labels DPI as **nominal, derived from scale factor**, not exact measured DPI. Custom scaling can be coarser than actual DPI and requires live validation. Physical pixel mapping does not rescale with that nominal value. Changing geometry/reported scale invalidates the snapshot; not all custom DPI changes are guaranteed observable as distinct scale enums.

Desktop BitBlt is a newly added, **live-Windows-unverified** backend. It can fail or omit protected/HDR/accelerated surfaces; cursor inclusion, mixed-monitor behavior and color correctness need manual checks. Nonuniform images do not prove GPU viewport correctness, completeness or freshness. Windows Graphics Capture is not implemented. No claim is made that CAD/Blender screenshots or interaction are universally supported.

## Verification scope

Fake tests cover valid/invalid regions, negative origins and mixed scale, boundary/large/overflow checks, config eligibility vs consent, expiry and changed scope, stop/timeout/crash/bad dimensions, post-encode revocation, absence of desktop input tickets and refusal of silent fallback. Native function bodies run with fake GDI objects to verify flush-before-read, negative BitBlt source coordinates, error branches and resource cleanup. Real disposable processes are exercised by worker tests. None calls real Windows screenshot APIs here.

Live checks remain in [WINDOWS_MANUAL_CHECKLIST.md](WINDOWS_MANUAL_CHECKLIST.md). Primary references: [BitBlt](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-bitblt), [CreateDIBSection](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createdibsection), [virtual screen](https://learn.microsoft.com/en-us/windows/win32/gdi/the-virtual-screen), [GetScaleFactorForMonitor](https://learn.microsoft.com/en-us/windows/win32/api/shellscalingapi/nf-shellscalingapi-getscalefactorformonitor). They guide implementation; they do not substitute for live Windows validation.
# Persistent owner profile option

The per-scope dialogs below describe default legacy authorization. The optional [owner profile](OWNER_PERMISSIONS.md) replaces repeat dialogs only for capture capabilities/apps explicitly selected at onboarding. Wider desktop modes still need local eligibility and their own selected capability, issue no input token, and refuse capture while an owner permission surface is open. Native permission-surface/mutex behavior remains live-Windows-unverified.
