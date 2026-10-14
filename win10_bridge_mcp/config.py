"""Local configuration shared by MCP parent and bounded native workers."""
import json
import os
from pathlib import Path
from .policy import normalize_allowlist
from .capture_policy import CAPTURE_MODES


def load_config() -> dict:
    cfgfile = Path(os.environ.get("WIN10_BRIDGE_CONFIG", str(Path.home() / "Win10_ComputerBridge" / "bridge_config.json")))
    cfg = {"allow_processes": ["notepad.exe"], "mouse_control_mode": "disabled",
           "semantic_control_mode": "disabled", "capture_modes": ["window"],
           "capture_consent_mode": "session"}
    if cfgfile.exists():
        raw = json.loads(cfgfile.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("Configuration must be JSON object")
        if set(raw) - {"allow_processes", "mouse_control_mode", "semantic_control_mode", "capture_modes", "capture_consent_mode", "notes"}:
            raise ValueError("Unexpected configuration keys")
        cfg.update(raw)
    cfg["allowed"] = normalize_allowlist(cfg["allow_processes"])
    if cfg["mouse_control_mode"] not in {"disabled", "foreground_confirm_each", "foreground_session"}:
        raise ValueError("mouse_control_mode must be disabled, foreground_confirm_each or foreground_session")
    if cfg["semantic_control_mode"] not in {"disabled", "app_confirm_each", "app_session"}:
        raise ValueError("semantic_control_mode must be disabled, app_confirm_each or app_session")
    modes = cfg["capture_modes"]
    if not isinstance(modes, list) or any(not isinstance(m, str) or m not in CAPTURE_MODES for m in modes) or len(set(modes)) != len(modes):
        raise ValueError("capture_modes must be a unique list of window, monitor, virtual_desktop, region (empty disables transmission)")
    if cfg["capture_consent_mode"] not in {"confirm_each", "session"}:
        raise ValueError("capture_consent_mode must be confirm_each or session")
    return cfg
