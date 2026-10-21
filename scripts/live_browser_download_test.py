"""Opt-in isolated real Edge/Chrome JavaScript blob download regression."""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--browser', choices=['edge', 'chrome'], required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.run:
        parser.error('--run is required; this opens an isolated fixture browser')
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    dest = root / 'downloads'
    dest.mkdir()
    profile = root / 'profile'
    (profile / 'Default').mkdir(parents=True)
    (profile / 'Default' / 'Preferences').write_text(json.dumps({
        'download': {'default_directory': str(dest), 'prompt_for_download': False},
        'browser': {'check_default_browser': False},
        'signin': {'allowed': False},  # Isolated fixture only; never inherit owner sign-in.
    }))
    cfg = root / 'bridge.json'
    exe = 'chrome.exe' if args.browser == 'chrome' else 'msedge.exe'
    cfg.write_text(json.dumps({'allow_processes': [exe], 'mouse_control_mode': 'foreground_session'}))
    os.environ['WIN10_BRIDGE_CONFIG'] = str(cfg)
    from win10_bridge_mcp import server, __version__, __file__ as package_file
    payload = b'TaskKit browser blob download fixture\n'
    filename = 'taskkit-blob-fixture.txt'
    html = root / 'fixture.html'
    html.write_text('''<!doctype html><meta charset="utf-8"><title>TaskKit download fixture</title>
    <h1>TaskKit isolated browser download test</h1>
    <button id="taskkit-download" onclick="try { document.title='TaskKit fixture clicked'; let a=document.createElement('a');
    a.href=window.URL.createObjectURL(new Blob(['TaskKit browser blob download fixture\\n'],{type:'text/plain'}));
    a.download='taskkit-blob-fixture.txt';document.body.appendChild(a);a.click();a.remove();document.body.append('Fixture download requested'); } catch(e) { document.body.append('Fixture error: '+e); }">
    TaskKit Blob Download</button>''', encoding='utf-8')
    binary = (Path(os.environ['PROGRAMFILES']) / 'Google/Chrome/Application/chrome.exe'
              if args.browser == 'chrome' else
              Path(os.environ['PROGRAMFILES(X86)']) / 'Microsoft/Edge/Application/msedge.exe')
    process = subprocess.Popen([str(binary), '--user-data-dir=' + str(profile), '--no-first-run',
                                '--no-default-browser-check', '--force-renderer-accessibility',
                                *(['--inprivate'] if args.browser == 'edge' else []), '--new-window', html.as_uri()])
    report = {'browser': args.browser, 'profile_isolated': True, 'package_version': __version__, 'package_file': package_file, 'inprivate': args.browser == 'edge'}
    try:
        server.start_control_session()
        deadline = time.monotonic() + 25
        target = None
        while time.monotonic() < deadline:
            wins = server.inspect_windows()['windows']
            report['startup_windows'] = wins
            report['browser_exit_code'] = process.poll()
            target = next((w for w in wins if 'TaskKit download fixture' in w['title']), None)
            if target:
                controls = server.inspect_controls(target['window_id'])['controls']
                if any(c['name'] == 'TaskKit Blob Download' and c['control_type'] == 50000 for c in controls):
                    break
            time.sleep(.5)
        else:

            if target:
                wid = target.get('blocked_by_window_id') or target['window_id']
                report['blocking_controls'] = server.inspect_controls(wid)['controls']
                image = server.capture_window(wid)
                (root / 'startup.png').write_bytes(base64.b64decode(image.content[1].data))
            raise AssertionError('Fixture window/button not exposed; inspect output before retrying')
        capture = server.capture_window(target['window_id'])
        info = json.loads(capture.content[0].text)
        report['capture'] = info
        (root / 'capture.png').write_bytes(base64.b64decode(capture.content[1].data))
        result = server.browser_download(target['window_id'], info['capture_id'], str(dest),
                                        control_name='TaskKit Blob Download', expected_filename=filename,
                                        dry_run=False)
        report['initial'] = result
        token = result['download_id']
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = server.browser_download_status(token)
            if result['status'] == 'file_observed':
                break
            time.sleep(.5)
        report['final'] = result
        report['controls_after'] = server.inspect_controls(target['window_id'])['controls']
        report['windows_after'] = [w['title'] for w in server.inspect_windows()['windows']
                                   if w['window_id'] == target['window_id']]
        final_capture = server.capture_window(target['window_id'])
        (root / 'after.png').write_bytes(base64.b64decode(final_capture.content[1].data))
        assert result['status'] == 'file_observed', result
        assert (dest / filename).read_bytes() == payload
        report['exact_fixture_bytes_verified'] = True
        report['passed'] = True
    finally:
        report['finish'] = server.end_control_session()
        (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        # Only our isolated fixture parent; never terminate the owner's browser.
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
    print(json.dumps({k: report[k] for k in ('browser', 'passed', 'final', 'exact_fixture_bytes_verified', 'finish')}, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
