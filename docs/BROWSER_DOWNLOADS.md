# Edge / Chrome download workflow

Developed by TaskKit.vn - Minh Long Tran.

## Why a download button can fail

`locator.downloadMedia` is a client browser API, not a TaskKit tool. A visible `<button>` can generate a JavaScript/blob download or start an authenticated request without exposing a downloadable URL on that element. Finding the button successfully does not make it a media URL. Updating TaskKit does not patch the client API.

## TaskKit alternative

1. The owner authorizes the computer task. Start a new control session if the previous task ended. Inspect windows, inspect controls and capture the actual Edge (`msedge.exe`) or Chrome (`chrome.exe`) window.
2. Identify a unique enabled UIA **button**, using exactly one `automation_id` or `control_name`. Supply the actual existing browser download directory. The bridge shares the real mouse/focus for the one click. It does not infer it, change preferences, or scan other directories.
3. Call `browser_download(window_id, capture_id, download_dir, control_name="Tải xuống", expected_filename="result.pdf")` for a dry run. Set `dry_run=False` to click once. The default protects against accidentally starting a download. Dry runs do not consume the capture or create receipts.
4. Record the returned `download_id`. After at least one second, call `browser_download_status(download_id)`. This is a non-blocking observation; the tool does not keep a background watcher or transport request waiting for a large file.
5. Verify the browser result and intended filename. Inspect/capture Save As or permission/security prompts explicitly and target their own window. Never automatically confirm prompts, disable browser protection, or repeat a click after an uncertain result.
6. Finish with `end_control_session`. Observing a receipt does not rearm input or clear cancellation/recovery.

Supported states:

| State | Meaning / next action |
| --- | --- |
| `waiting` | No matching changed file yet. Inspect browser prompts or the configured destination; do not click again automatically. |
| `in_progress` | Changed `.crdownload`, `.tmp`, `.part`, `.partial` or `.download` files remain. |
| `settling` | A matching final-name file appeared but is not stable for one second yet. |
| `file_observed` | One final-name file has stable size/mtime across observations, with no changed partial file. Check browser completion and source separately. |
| `needs_review` | Multiple candidates or a changed pre-existing file; do not claim success. |
| `observation_error` | The destination became unavailable or too large; the receipt is preserved. Inspect the directory without clicking again. |
| `action_uncertain` | Invocation raised/ timed out. Inspect windows and capture to satisfy native recovery, then observe the receipt. Never replay automatically. |

`source_verified` is always false: directory observation cannot associate a file with a browser request. Supply an exact expected filename and use a dedicated destination for stronger evidence. An existing expected filename is refused before input to avoid overwriting; browser-generated suffixes need manual review. Zero-byte downloads can be legitimate and are not silently discarded. File disappearance or continued writes reset stability. No file content, credentials, browser database or URL is read. Reports include local filenames and paths and are sent to the MCP client.

Only existing absolute local directories are accepted. Symlink files are skipped, scans are nonrecursive and limited to 5,000 entries. At most 32 receipts live for one hour, in the current MCP process; reconnecting drops them. Downloads moved elsewhere are not tracked. Partial filenames and stability are heuristics, not proof of a successful server response.

If a browser does not expose the page button through UIA, TaskKit refuses safely. Use a fresh window capture and the ordinary `click_left` workflow, then verify the browser/downloaded file separately. This tool always uses one guarded physical left click after UIA identification; it never tries UIA invocation first or retries through another method. It does not attach debugging ports. Links and canvas controls are not supported by `browser_download`.

## Updating

Run the existing Windows installer from this source checkout and reconnect the MCP once. Existing bridge configuration is preserved. `bridge_status.version` should report `0.5.0`; the tool list should include both download tools. A connected old server does not automatically acquire new tools.

## Validation

Run `python -m pytest -q` and `python scripts/smoke_test.py`. The opt-in `scripts/live_browser_download_test.py --run --browser chrome|edge --out <dedicated directory>` creates its own isolated browser profile and local fixture (Edge uses InPrivate to avoid the fresh-profile sync dialog), clicks a JavaScript blob button through TaskKit, and verifies exact fixture bytes. It never uses the owner's normal browser profile or external website. These fixtures do not certify every website, policy, Save As dialog or protected download.
