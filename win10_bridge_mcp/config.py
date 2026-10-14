"""Local configuration shared by MCP parent and bounded native workers."""
import json
import os
from pathlib import Path
from .policy import normalize_allowlist


def load_config() -> dict:
    cfgfile = Path(os.environ.get("WIN10_BRIDGE_CONFIG", str(Path.home() / "Win10_ComputerBridge" / "bridge_config.json")))
    cfg = {"allow_processes": ["notepad.exe"], "mouse_control_mode": "disabled",
           "semantic_control_mode": "disabled"}
    if cfgfile.exists():
        raw = json.loads(cfgfile.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("Configuration must be JSON object")
        if set(raw) - {"allow_processes", "mouse_control_mode", "semantic_control_mode", "notes"}:
            raise ValueError("Unexpected configuration keys")
        cfg.update(raw)
    cfg["allowed"] = normalize_allowlist(cfg["allow_processes"])
    if cfg["mouse_control_mode"] not in {"disabled", "foreground_confirm_each", "foreground_session"}:
        raise ValueError("mouse_control_mode must be disabled, foreground_confirm_each or foreground_session")
    if cfg["semantic_control_mode"] not in {"disabled", "app_confirm_each", "app_session"}:
        raise ValueError("semantic_control_mode must be disabled, app_confirm_each or app_session")
    return cfg

