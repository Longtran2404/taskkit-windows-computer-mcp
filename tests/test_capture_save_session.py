from dataclasses import replace
from io import BytesIO
import pytest
from win10_bridge_mcp import server, ui_access
from win10_bridge_mcp.policy import Rect


@pytest.mark.parametrize('fault', ['stop', 'identity', 'resize', 'dpi', 'blank', 'dimensions', 'timeout', 'crash'])
def test_capture_rejects_changed_or_failed_frame(bridge, fault):
    native, _ = bridge
    before = native.current
    def hook():
        if fault == 'stop': native.SESSION_STOP.set()
        if fault == 'identity': native.current = replace(before, id='new')
        if fault == 'resize': native.current = replace(before, rect=Rect(0, 0, 900, 800))
        if fault == 'dpi': native.current = replace(before, dpi=192)
    native.capture_hook = hook
    original = native.capture_window
    if fault in {'blank', 'dimensions', 'timeout', 'crash'}:
        def capture(win):
            if fault == 'timeout': raise TimeoutError('worker deadline')
            if fault == 'crash': raise RuntimeError('worker crash')
            png, method, _ = original(win)
            if fault == 'dimensions':
                from PIL import Image
                out = BytesIO(); Image.new('RGB', (1, 1)).save(out, 'PNG'); png = out.getvalue()
            return png, method, fault == 'blank'
        native.capture_window = capture
    with pytest.raises((ValueError, InterruptedError, RuntimeError, TimeoutError)):
        server.capture_window(before.id)
    assert not server.REGISTRY._tickets


def test_capture_reports_mapping_and_uncertainty(bridge):
    native, _ = bridge
    result = server.capture_window(native.current.id)
    info = result.structuredContent
    assert info['origin'] == [-1200, -200]
    assert info['dpi'] == 144
    assert info['status'] == 'best_effort_unverified'
    assert not info['gpu_viewport_verified']
    assert info['timestamp_utc']
    assert result.content[1].type == 'image'


@pytest.mark.parametrize('text', ['a\r\nb\r\n', 'a\nb\n', 'Tiếng Việt', 'emoji 😀', '', '\ufeffliteral'])
@pytest.mark.parametrize('exists', [False, True])
def test_save_exact_newlines_unicode_bom(bridge, ticket, monkeypatch, tmp_path, text, exists):
    native, _ = bridge
    p = tmp_path/'saved.txt'
    if exists:
        p.write_bytes(b'\xef\xbb\xbf' + text.encode('utf-8'))
    monkeypatch.setattr(ui_access, 'value', lambda *_, **kw: text)
    result = server.save_notepad_text(native.current.id, ticket, str(p), False, False)
    assert result['saved_verified']
    assert p.read_bytes() == (b'\xef\xbb\xbf' if exists else b'') + text.encode('utf-8')


def test_existing_different_newlines_preserved(bridge, ticket, monkeypatch, tmp_path):
    native, _ = bridge
    p=tmp_path/'existing.txt'; p.write_bytes(b'keep\r\n')
    monkeypatch.setattr(ui_access, 'value', lambda *_, **kw: 'keep\n')
    with pytest.raises(FileExistsError): server.save_notepad_text(native.current.id, ticket, str(p), False, False)
    assert p.read_bytes() == b'keep\r\n'


def test_exclusive_create_race_preserves_winner(bridge, ticket, monkeypatch, tmp_path):
    native, _ = bridge
    p=tmp_path/'race.txt'
    monkeypatch.setattr(ui_access, 'value', lambda *_, **kw: 'mine')
    from pathlib import Path
    original = Path.open
    def raced(path, mode='r', *args, **kwargs):
        if path == p and mode == 'x':
            p.write_bytes(b'winner')
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', raced)
    with pytest.raises(FileExistsError): server.save_notepad_text(native.current.id, ticket, str(p), False, False)
    assert p.read_bytes() == b'winner'


def test_session_config_needs_dialog_expires_and_stop_never_rearms(bridge, monkeypatch):
    native, cfg = bridge
    dialogs = []
    monkeypatch.setattr(server, 'ask_local_consent', lambda text: dialogs.append(text) or True)
    server.require_session(cfg)
    server.require_session(cfg)
    assert len(dialogs) == 1
    server.CONSENT.expires = 0
    with pytest.raises(PermissionError): server.action_guard(cfg, native)
    server.require_session(cfg)
    assert len(dialogs) == 2
    native.SESSION_STOP.set()
    with pytest.raises(InterruptedError): server.require_session(cfg)
    assert len(dialogs) == 2


def test_decline_cannot_arm_from_mcp(bridge, monkeypatch):
    _, cfg = bridge
    monkeypatch.setattr(server, 'ask_local_consent', lambda _: False)
    with pytest.raises(PermissionError): server.require_session(cfg)
    assert not server.CONSENT.armed(cfg)


def test_capture_is_read_only_and_does_not_arm_session(bridge, monkeypatch):
    native, cfg = bridge
    monkeypatch.setattr(server, 'ask_local_consent', lambda _: pytest.fail('read requested input consent'))
    server.capture_window(native.current.id)
    assert not server.CONSENT.armed(cfg)


@pytest.mark.parametrize('fault', ['stop', 'dpi', 'identity', 'expired'])
def test_recheck_after_human_consent_blocks_input(bridge, ticket, monkeypatch, fault):
    native, cfg = bridge
    cfg['mouse_control_mode'] = 'foreground_confirm_each'
    before = native.current
    def ask(_):
        if fault == 'stop': native.SESSION_STOP.set()
        if fault == 'dpi': native.current = replace(before, dpi=192)
        if fault == 'identity': native.current = replace(before, id='reused')
        if fault == 'expired': server.REGISTRY.ttl = 0
        return True
    monkeypatch.setattr(server, 'ask_local_consent', ask)
    with pytest.raises((ValueError, InterruptedError)):
        server.mouse_action(before.id, ticket, 'click', 10, 10, dry_run=False)
    assert not native.operations


def test_stop_during_response_encoding_discards_image_token(bridge, monkeypatch):
    native, _=bridge
    original=server.base64.b64encode
    def encode(value):
        native.SESSION_STOP.set()
        return original(value)
    monkeypatch.setattr(server.base64, 'b64encode', encode)
    with pytest.raises(InterruptedError): server.capture_window(native.current.id)
    assert not server.REGISTRY._tickets


def test_config_change_invalidates_existing_consent(bridge, monkeypatch):
    native, cfg=bridge
    server.require_session(cfg)
    replacement=dict(cfg, allowed=frozenset({'notepad.exe', 'explorer.exe'}))
    monkeypatch.setattr(server, 'load_config', lambda: replacement)
    with pytest.raises(PermissionError): server.action_guard(cfg, native)
    assert not server.CONSENT.armed(replacement)


@pytest.mark.parametrize('mode', ['disabled', 'foreground_confirm_each', 'foreground_session'])
def test_dry_run_never_arms_sends_or_consumes(bridge, ticket, monkeypatch, mode):
    native, cfg=bridge
    cfg['mouse_control_mode']=mode
    monkeypatch.setattr(server, 'ask_local_consent', lambda _: pytest.fail('dry run asked consent'))
    assert server.mouse_action(native.current.id, ticket, 'click', 20, 20)['dry_run']
    assert server.type_text(native.current.id, ticket, 'x')['dry_run']
    assert server.press_key(native.current.id, ticket, 's')['dry_run']
    assert ticket in server.REGISTRY._tickets
    assert not native.operations
    assert not server.CONSENT.armed(cfg)
