import json
import pytest
pytest.importorskip('mcp')
from win10_bridge_mcp.server import load_config


def test_default_no_mouse(monkeypatch, tmp_path):
    monkeypatch.setenv('WIN10_BRIDGE_CONFIG', str(tmp_path/'not-there.json'))
    cfg = load_config()
    assert cfg['mouse_control_mode'] == 'disabled'
    assert cfg['authorization_mode'] == 'legacy'
    assert cfg['allowed'] == frozenset({'notepad.exe'})


def test_explicit_arming(monkeypatch, tmp_path):
    path = tmp_path/'config.json'
    path.write_text(json.dumps({'allow_processes':['Revit.exe'], 'mouse_control_mode':'foreground_confirm_each'}))
    monkeypatch.setenv('WIN10_BRIDGE_CONFIG', str(path))
    assert load_config()['allowed'] == {'revit.exe'}


def test_reject_bad_config(monkeypatch, tmp_path):
    path = tmp_path/'config.json'
    path.write_text(json.dumps({'allow_processes':['notepad.exe'], 'mouse_control_mode':'background_injection'}))
    monkeypatch.setenv('WIN10_BRIDGE_CONFIG', str(path))
    with pytest.raises(ValueError): load_config()


def test_reject_automatic_computer_use_permissions(monkeypatch,tmp_path):
    path=tmp_path/'config.json'
    path.write_text(json.dumps({'authorization_mode':'inherit_chatgpt'}))
    monkeypatch.setenv('WIN10_BRIDGE_CONFIG',str(path))
    with pytest.raises(ValueError):load_config()
