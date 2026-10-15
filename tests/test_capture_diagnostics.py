import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from win10_bridge_mcp import server, desktop, recovery, viewer


@pytest.fixture
def setup(monkeypatch):
    native = SimpleNamespace(get_window=Mock(return_value=SimpleNamespace(id='1:abc')),
                             capture_window=Mock(return_value=(b'window', 'PrintWindow full', False)))
    monkeypatch.setattr(server, 'backend', lambda: native)
    monkeypatch.setattr(server, 'load_config', lambda: {'allowed': {'*'}})
    monkeypatch.setattr(server.REGISTRY, 'issue', lambda *_: pytest.fail('Diagnostic issued an input ticket'))
    monkeypatch.setattr(server.REGISTRY, 'invalidate_all', lambda: pytest.fail('Diagnostic changed tickets'))
    monkeypatch.setattr(recovery, 'captured', lambda *_: pytest.fail('Diagnostic cleared recovery'))
    monkeypatch.setattr(server, 'require_session', lambda *_: pytest.fail('Diagnostic armed input'))
    return native


def read(result):
    return json.loads(result.content[0].text)


def test_diagnostic_success_is_read_only_and_no_implicit_desktop(setup, monkeypatch):
    monkeypatch.setattr(desktop, 'capture', lambda *_: pytest.fail('Implicit desktop capture'))
    viewer.STOP.set()
    try:
        result = server.diagnose_capture('1:abc')
        info = read(result)
        assert info['window_capture']['status'] == 'captured'
        assert info['image_order'] == ['window']
        assert not info['input_ticket_issued'] and not info['requires_sky']
        assert viewer.STOP.is_set() and len(result.content) == 2
    finally:
        viewer.STOP.clear()


@pytest.mark.parametrize('failure', [TimeoutError('provider timed out'), RuntimeError('PrintWindow failed'), OSError('GDI failed')])
def test_failed_window_can_return_explicit_desktop_observation(setup, monkeypatch, failure):
    setup.capture_window.side_effect = failure
    monkeypatch.setattr(desktop, 'capture', lambda *_: (b'desktop', {'origin_x': -1920, 'origin_y': 0}))
    result = server.diagnose_capture('1:abc', include_desktop=True)
    info = read(result)
    assert info['window_capture']['status'] == 'failed'
    assert info['window_capture']['error_type'] == type(failure).__name__
    assert info['desktop_capture']['origin_x'] == -1920
    assert info['image_order'] == ['desktop'] and len(result.content) == 2
    setup.capture_window.assert_called_once()


def test_blank_window_is_not_returned_as_valid_image(setup):
    setup.capture_window.return_value = (b'blank', 'PrintWindow basic', True)
    result = server.diagnose_capture('1:abc')
    assert read(result)['window_capture']['status'] == 'possibly_blank'
    assert read(result)['image_order'] == [] and len(result.content) == 1


def test_desktop_requires_all_app_scope_before_capture(setup, monkeypatch):
    monkeypatch.setattr(server, 'load_config', lambda: {'allowed': {'notepad.exe'}})
    with pytest.raises(PermissionError):
        server.diagnose_capture('1:abc', include_desktop=True)
    setup.get_window.assert_not_called()
    setup.capture_window.assert_not_called()


def test_missing_target_is_not_hidden_as_a_capture_failure(setup):
    setup.get_window.side_effect = ValueError('Window missing')
    with pytest.raises(ValueError, match='Window missing'):
        server.diagnose_capture('1:abc')
    setup.capture_window.assert_not_called()


def test_failed_desktop_keeps_original_capture_failure(setup, monkeypatch):
    setup.capture_window.side_effect = TimeoutError('native timeout')
    def fail(*_):
        raise OSError('No interactive desktop')
    monkeypatch.setattr(desktop, 'capture', fail)
    info = read(server.diagnose_capture('1:abc', include_desktop=True))
    assert info['window_capture']['error'] == 'native timeout'
    assert info['desktop_capture']['status'] == 'failed' and info['image_order'] == []


def test_invalid_desktop_size_refused_before_native_capture(setup):
    with pytest.raises(ValueError, match='max_edge'):
        server.diagnose_capture('1:abc', include_desktop=True, max_edge=100000)
    setup.capture_window.assert_not_called()
