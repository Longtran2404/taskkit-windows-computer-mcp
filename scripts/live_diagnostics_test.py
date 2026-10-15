"""Opt-in diagnostic check against its own disposable window; no physical input."""
import argparse
import asyncio
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(out):
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    config = out / 'config.json'
    config.write_text(json.dumps({'allow_processes': ['*'], 'mouse_control_mode': 'foreground_session'}))
    env = dict(os.environ, WIN10_BRIDGE_CONFIG=str(config), PYTHONUTF8='1')
    fixture = subprocess.Popen([sys.executable, str(Path(__file__).with_name('live_mouse_fixture.py')),
                                '--out', str(out), '--keep-open-on-escape'], env=env)
    try:
        async with stdio_client(StdioServerParameters(command=sys.executable, args=['-m', 'win10_bridge_mcp'], env=env)) as (r, w):
            async with ClientSession(r, w) as client:
                await client.initialize()
                async def call(name, args=None):
                    result = await client.call_tool(name, args or {})
                    assert not result.isError, (name, result)
                    return json.loads(result.content[0].text), result
                for _ in range(80):
                    if fixture.poll() is not None:
                        raise RuntimeError('Diagnostic fixture exited before discovery')
                    try:
                        fixture_pid = json.loads((out / 'fixture.json').read_text(encoding='utf-8'))['pid']
                    except (OSError, ValueError, KeyError):
                        await asyncio.sleep(.1)
                        continue
                    wins, _ = await call('inspect_windows')
                    target = next((win for win in wins['windows'] if win['pid'] == fixture_pid), None)
                    if target:
                        break
                    await asyncio.sleep(.1)
                assert target, 'Fixture window not found'
                # Diagnose after finishing: reads must not rearm or show controls.
                await call('end_control_session')
                before, _ = await call('bridge_status')
                meta, result = await call('diagnose_capture', {'window_id': target['window_id'], 'include_desktop': True})
                assert meta['window_capture']['status'] == 'captured', meta
                assert meta['desktop_capture']['status'] == 'captured', meta
                assert not meta['input_ticket_issued'] and meta['image_order'] == ['window', 'desktop']
                dimensions = []
                for content in result.content[1:]:
                    image = Image.open(BytesIO(base64.b64decode(content.data)))
                    image.load()
                    dimensions.append(list(image.size))
                    assert image.width > 100 and image.height > 50
                after, _ = await call('bridge_status')
                assert before['session_stopped'] and after['session_stopped']
                assert not after['control_indicator_active'] and not after['live_view']['visible']
                assert after['timeout_recovery'] == before['timeout_recovery']
                assert fixture.poll() is None
                report = {'version': after['version'], 'tool_count': len((await client.list_tools()).tools),
                          'window_capture': meta['window_capture'], 'desktop_captured': True,
                          'monitor_count': len(meta['desktop_capture']['monitors']), 'image_dimensions': dimensions,
                          'session_remained_stopped': True, 'no_overlays': True,
                          'timeout_gate_preserved': True, 'fixture_preserved': True}
                (out / 'report.json').write_text(json.dumps(report, indent=2))
                print(json.dumps(report), flush=True)
                await call('end_control_session')
    finally:
        (out / 'close.request').touch()
        try:
            fixture.wait(5)
        except subprocess.TimeoutExpired:
            fixture.terminate()
            fixture.wait(5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.run:
        parser.error('Requires --run; desktop observation can include other applications')
    asyncio.run(main(args.out))
