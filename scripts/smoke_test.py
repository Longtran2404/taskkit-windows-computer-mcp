"""Owner-run live MCP protocol smoke test."""
import asyncio
import sys
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    env = {key: os.environ[key] for key in ("WIN10_BRIDGE_CONFIG", "PYTHONPATH") if key in os.environ}
    p = StdioServerParameters(command=sys.executable, args=["-m", "win10_bridge_mcp"], env=env)
    async with stdio_client(p) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = sorted(t.name for t in listed.tools)
            print("MCP TOOLS:", ", ".join(names))
            assert {"bridge_status", "inspect_windows", "capture_window",
                    "mouse_action", "emergency_release", "show_live_view", "close_live_view",
                    "type_text", "press_key", "inspect_controls", "control_action",
                    "open_directory", "list_drives", "save_notepad_text",
                    "click_left", "click_right", "click_middle", "scroll_mouse", "app_control", "start_control_session",
                    "list_monitors", "capture_desktop"} <= set(names)
            result = await session.call_tool("bridge_status")
            print("STATUS:", [getattr(c, "text", None) for c in result.content])


if __name__ == "__main__":
    asyncio.run(main())
