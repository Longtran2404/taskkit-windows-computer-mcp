# Owner-run Windows checklist — candidate 0.4.2.dev1

**All items below are pending.** Linux cloud tests do not execute this checklist. Use a disposable Windows desktop/VM, test files and a visibly identified Notepad window. Record OS build, interpreter/architecture, DPI per monitor, app version, privileges, candidate commit, expected/actual outcome and worker exit/process counts. Keep screenshots local unless the owner explicitly chooses MCP transmission.

## Installation and protocol

- [ ] Extract full source; inspect LICENSE/NOTICE and default disabled config. Run the non-admin installer with Python 3.11, then separately 3.13; repeat installation and confirm there is no nested/stale package path. Verify package version `0.4.2.dev0` and `pip check`.
- [ ] Test paths with spaces and Unicode. Confirm existing config bytes survive. Confirm `-InstallCodex` is the sole registration opt-in; omit it when registration should not change. Installer must not modify execution policy or request elevation.
- [ ] Verify Tkinter preview availability. Run `python -m pytest -q` and `python scripts/smoke_test.py`. The ABI test should pass on Windows; remaining adapter tests are still simulations. Smoke uses disabled config and sends no input.
- [ ] Start MCP stdio from the installed wheel outside the checkout. Check 17 tools, structured status, dry-run defaults and `isError` on invalid input. Confirm no network listener is opened.

## Consent and permanent stop

- [ ] With `disabled`, verify capture/inspection work and all physical/semantic mutations fail even with `dry_run=false`. Dry runs never prompt or consume a token.
- [ ] In `foreground_confirm_each`, verify a local native dialog for every finite physical operation; No/timeout sends no input. Stop while the dialog is open; it must disappear and no action run after Yes.
- [ ] In `foreground_session`, config alone must leave `session_armed=false`. First mutation prompts locally; No blocks it. Yes authorizes only the displayed allowlist/mode for at most 5 minutes. Status/capture never prompt/arm. Expiry requires a new Yes; configuration changes invalidate the existing grant.
- [ ] Hold Esc and F12 in each mode during capture/UIA, click delay, second double-click, modifier stages, hold, every drag step, text and Ctrl+A. After release, capture/inspection/input/UIA must remain stopped. Hold duration should exceed the polling interval; record any missed pulses without claiming reliability for arbitrary brief taps.
- [ ] Close preview via Esc, F12 and window X; call `close_live_view` and separately `emergency_release`. Verify both parent and preview capture worker stop. Opening preview cannot clear the latch. Check stopped status. Restart locally to resume and approve consent again.
- [ ] Race preview startup against a deliberate stop. Confirm no new frame/input and no leaked preview/native worker. Missing Tkinter/window must report a useful startup reason.

## Capture, coordinates and identity

- [ ] For 100%, 150% and 200% monitors, including negative X/Y origins, compare PNG dimensions/origin/DPI to the physical outer-window rectangle. Verify precise intended test coordinates on image and target before input; invisible borders can be included.
- [ ] Move/resize/change DPI/minimize/destroy or restart the target while capture is in progress and after a token. Changed mapping/identity must yield no image/token or refuse the stale token. Verify fresh IDs include process creation time and old IDs are rejected.
- [ ] Test occluded and GPU/accelerated windows with a known reference scene. A nonuniform image is not sufficient: verify viewport contents and freshness visually. Blank/uniform captures must produce no click token. Confirm no whole-desktop fallback.
- [ ] Use a controlled test window whose PrintWindow blocks/crashes. Confirm response by the configured deadline plus bounded termination/scheduling overhead, worker process reaped, no late token and next capture independent. Measure cold start, large frame and CPU-load behavior. Check temporary result directories are removed.
- [ ] Review CPU/memory/GDI handles during repeated previews. Confirm closing preview cancels its current capture worker. Validate incompatible DPI-awareness state fails with diagnostics.

## Input and cleanup

- [ ] Click left/right/middle/X1/X2; double click; move; bounded drag/hold; vertical/horizontal wheel with positive/negative ticks; Ctrl/Shift/Alt/Space combinations. Verify intended application result separately from submitted-event success.
- [ ] Enable cursor clipping for a controlled test region. Requested point outside it must be refused after actual `GetCursorPos`, with no down/wheel event. Cover the point with another window/overlay or steal focus before each stage; abort and release only transaction-owned downs.
- [ ] Move the real cursor or press an unrelated physical key during an operation. Verify abort without broad normal cleanup. Hold a key/button before starting; it must refuse without releasing that input. Test swapped mouse buttons and touch/pen input explicitly; their semantics have not been verified.
- [ ] Test asynchronous key/button-up state on a busy desktop. A successful up should settle before the next effect; failure to settle within 150 ms must abort with no repeated release. Stop/focus/geometry checks continue during settling.
- [ ] Press the exact same physical key/button the transaction holds. **Known limitation:** asynchronous key state does not distinguish physical from injected ownership. Document observed behavior; do not certify preservation of that physical hold. Use a separate desktop/app API when that distinction is required.
- [ ] Type Vietnamese and emoji, test Ctrl+A replacement and chord order. Steal focus during each Ctrl+A/text stage; no later text should reach another window. Verify focused editor selection and resulting text, including surrogate pairs.
- [ ] Use an elevated target to check UIPI refusal. Do not elevate the bridge to bypass it. Exercise injected down/up failure; normal cleanup must report failure, and explicit emergency release must be labelled best effort (it can affect owner-held input).

## UIA and files

- [ ] Inspect controls on supported Notepad versions; password controls omitted, ambiguous/disabled IDs refused. Verify SetValue/Invoke only after local consent and foreground identity/geometry checks.
- [ ] Test slow/crashed COM providers and focus/stop/expiry while resolving patterns or inside a mutation. Worker killed by deadline; no late accepted result. A mutation dispatched to the app may complete after cancellation; inspect actual state before retrying.
- [ ] Save a **copy** with CRLF, LF, Vietnamese, emoji, empty text, UTF-8 BOM and literal initial U+FEFF. Compare exact UTF-8 bytes/newlines. Matching existing files remain byte-identical; differing files and concurrent exclusive-create winners are preserved.
- [ ] Try relative/UNC/device/mapped-network/alternate-stream destinations and reparse links; verify local-path policy refusal where applicable. Canonical-path checks do not eliminate concurrent reparse/filesystem races and do not form a sandbox.
- [ ] Verify `open_saved=false` launches nothing. With it enabled, confirm a new Notepad opens the copy and the original editor remains unchanged/unsaved. For original Save As, verify both title/state and disk bytes.
- [ ] Allowlist Explorer explicitly, approve session, open an existing local directory and verify the resulting Explorer window. Invocation/open requests alone do not prove completion.

Do not publish compatibility claims until the relevant items are recorded as passed. CAD/3D, GPU correctness, background concurrent physical input and all live Windows outcomes remain outside this cloud's verification.

## App-only feature (all pending on live Windows)

- [ ] Keep physical mode disabled; enable app_confirm_each/app_session locally. Verify its separate local consent, shown payload, 5-minute expiry, one-window scope, config-change invalidation and stop latch. Status must show only an active app grant and remaining lifetime.
- [ ] With a different window foreground and a supported, non-minimized target behind it, perform Value/Invoke/Select/Scroll. Record cursor/focus before/after and actual API calls if instrumented. The bridge must never call SetCursorPos/SendInput/SetForegroundWindow/SetFocus/PostMessage for the operation. Consent dialog requires local owner interaction; distinguish any provider-driven focus change.
- [ ] Verify missing/read-only/disabled/unsupported-axis patterns return structured errors without input/focus fallback. Confirm empty/duplicate IDs and password controls are refused without value/name reads.
- [ ] Reparent a same-process control to another overlapping window, replace its UIA root, change PID/bounds/password during pattern resolution, stop or expire/change consent before the effect. Refuse; no other window/control should be mutated.
- [ ] Validate selection readback and scroll percentages/at-boundary behavior. A provider-dispatched action after timeout may complete; inspect before retry. Multi-process providers, invisible/off-window virtualized controls and deep (>64) trees can be refused by scope checks.
- [ ] Do not claim CAD/Blender viewport background mouse support from passing generic UIA tests. Use a verified app API or separate desktop for that requirement.

## Explicit capture modes (all pending on live Windows)

- [ ] Confirm default window-only eligibility. Broad mode config alone does not transmit pixels: decline/timeout local data-sharing consent; no image/result. Confirm legacy capture_window also uses this consent without arming input. An empty capture_modes list disables MCP image transmission.
- [ ] Discover geometry without capture/consent. Capture selected monitor, all-monitor virtual desktop and signed absolute region on layouts with negative origins, gaps, mixed 100/150/200% scaling and custom scaling. Validate exact dimensions/origin/pixels; desktop DPI is nominal scale-derived and labelled accordingly.
- [ ] Test out-of-bounds, zero/negative dimensions, Win32 overflow and >12MP images. Reject, with no implicit scale/clamp/wider capture. Verify failed PrintWindow does not fall back to desktop. Verify monitor scope and region rectangle shown in native consent are correct.
- [ ] After capture scope consent, repeat exact scope, change region/mode/monitor/config, expire consent, stop mid-worker and hot-plug/change display geometry/scale. Require new consent or discard/stop; no stale image accepted. Status must not show stale capture grants.
- [ ] Inspect resource/process counts during repeated BitBlt captures and forced GetDC/CreateDC/DIB/SelectObject/BitBlt/GdiFlush failures. Confirm buffers flushed before reads and all handles released; crashed/late/hung workers reaped. Record deadline plus cleanup/scheduling overhead.
- [ ] Verify protected/HDR/GPU surfaces and cursor inclusion against known content. Do not infer correctness from nonuniform pixels. Desktop modes can expose other apps/secrets; approve only controlled test contents and keep images local unless explicitly choosing MCP sharing.
- [ ] Desktop capture_id is null; observation_id cannot authorize mouse/key/app-only mutations. Recapture an allowlisted app and separately authorize its mutation. No permissions extend to another app merely because it appears in desktop pixels.
## Optional persistent owner profile (0.4.2.dev1)

- [ ] In the owner input desktop, run `--permissions`: all checkboxes unchecked, app/capability dependencies explained, profile only written after explicit selections/owner confirmation. Installer `-OwnerOnboarding` must not enable persistent mode or register a secret automatically.
- [ ] Check current-user DPAPI round-trip/tamper/wrong-user failures, owner/SYSTEM ACLs, no plaintext secret in files/logs/args/MCP/image output, no secret inherited by native child. Use synthetic keys/data; keep credential values private.
- [ ] Verify protected root/owned dialogs cannot be enumerated/captured/mutated even with generic `python.exe` eligibility. Desktop capture must refuse while onboarding or any bridge consent dialog is open; simultaneous capture/UI startup is serialized by the named mutex.
- [ ] Configure a host's secure environment out of band; no secret copied into chat/source/command args. Authenticate that profile, change window within approved app without another dialog, and refuse app/capability/expired/wrong-key/other-profile/reinitialize requests.
- [ ] Close an idle connection and reconnect: credential verification and new lease/tokens, existing valid policy reused. Cancel a native operation, interrupt cleanup, kill bridge or disconnect with preview alive: running marker blocks automatic reuse. Owner local recover after inspecting state; revoke must never be overwritten by old cleanup/release.
- [ ] Esc/F12/owner preview close permanently stops current process and pauses policy across restart; inject a pause-write failure and ensure running marker blocks reconnect. Owner Pause/Resume require fresh connection; revoked credentials cannot resume.
- [ ] Call `bridge_health` from actual host: distinguish same-session different-desktop, unavailable input desktop/foreground, noninteractive session and owner Default context. Do not SwitchDesktop/elevate/bypass sandbox to make a check pass.
- [ ] Fresh window tokens, identity/geometry/DPI/hit/focus and owned-key cleanup still apply to real physical input. No UIA or physical fallback on unsupported patterns. Observe real operation result before claiming success.
