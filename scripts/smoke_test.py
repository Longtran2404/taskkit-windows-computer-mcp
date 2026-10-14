"""Read-only stdio assertions, isolated disabled config; never arm desktop input."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    with tempfile.TemporaryDirectory(prefix='taskkit-smoke-') as directory:
        config = Path(directory)/'bridge_config.json'
        config.write_text(json.dumps({'allow_processes': ['notepad.exe'], 'mouse_control_mode': 'disabled'}))
        env = dict(os.environ, WIN10_BRIDGE_CONFIG=str(config))
        p = StdioServerParameters(command=sys.executable, args=['-m', 'win10_bridge_mcp'], env=env)
        async with stdio_client(p) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = sorted(t.name for t in listed.tools)
                expected = {'bridge_status', 'inspect_windows', 'capture_window', 'mouse_action',
                            'emergency_release', 'show_live_view', 'close_live_view', 'type_text',
                            'press_key', 'inspect_controls', 'control_action', 'open_directory',
                            'list_drives', 'save_notepad_text', 'app_control_action'}
                assert expected == set(names)
                print('MCP TOOLS:', ', '.join(names))
                result = await session.call_tool('bridge_status')
                assert not result.isError
                status = result.structuredContent
                assert status['mouse_mode'] == 'disabled'
                assert not status['session_armed']
                assert status['capture']['desktop_fallback'] is False
                assert status['capture']['gpu_viewport_verified'] is False
                assert status['concurrent_desktop_mouse'] is False
                assert status['app_only']['mode'] == 'disabled'
                assert status['app_only']['physical_input_fallback'] is False
                assert status['app_only']['bridge_changes_focus'] is False
                assert status['timestamp_utc']
                error = await session.call_tool('type_text', {'window_id': 'invalid', 'capture_id': 'invalid', 'text': ''})
                assert error.isError is True
                assert error.structuredContent['error']['code'] == 'invalid_request'
                for tool in listed.tools:
                    if tool.name in {'mouse_action', 'type_text', 'press_key', 'control_action', 'save_notepad_text', 'app_control_action'}:
                        assert tool.inputSchema['properties']['dry_run']['default'] is True
                print('PASS: handshake, 15 schemas, physical/semantic disabled, unarmed status, structured errors/isError, safe defaults')


if __name__ == '__main__':
    asyncio.run(main())
