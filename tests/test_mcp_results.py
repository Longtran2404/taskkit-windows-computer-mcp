import asyncio
import pytest
from mcp.types import CallToolResult
from win10_bridge_mcp import server


@pytest.mark.parametrize('exception,code', [
    (TimeoutError('deadline'), 'native_timeout'),
    (RuntimeError('worker crashed'), 'operation_failed'),
    (InterruptedError('stop'), 'stop_or_intervention'),
    (PermissionError('denied'), 'permission_denied'),
    (ValueError('bad window'), 'invalid_request'),
    (OSError('capture failed'), 'native_or_file_error')])
def test_mcp_capture_structured_error_and_no_image_token(bridge, exception, code):
    native, _=bridge
    def fail(win): raise exception
    native.capture_window=fail
    result=asyncio.run(server.mcp.call_tool('capture_window', {'window_id': native.current.id}))
    assert isinstance(result, CallToolResult)
    assert result.isError
    assert result.structuredContent['error']['code']==code
    assert result.structuredContent['error']['effects_verified'] is False
    assert all(item.type=='text' for item in result.content)
    assert not server.REGISTRY._tickets


def test_mcp_disabled_input_never_sends(bridge, ticket):
    native, cfg=bridge
    cfg['mouse_control_mode']='disabled'
    result=asyncio.run(server.mcp.call_tool('mouse_action', {
        'window_id': native.current.id, 'capture_id': ticket, 'action': 'click',
        'x': 10, 'y': 10, 'dry_run': False}))
    assert result.isError
    assert result.structuredContent['error']['code']=='permission_denied'
    assert not native.operations
