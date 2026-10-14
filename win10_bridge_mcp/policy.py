"""Side-effect-free input validation and screenshot authorization rules."""
from __future__ import annotations

from dataclasses import dataclass
import re
import time
import uuid

DEFAULT_ALLOWED = ("notepad.exe",)
VALID_BUTTONS = frozenset({"left", "right", "middle", "x1", "x2"})
VALID_ACTIONS = frozenset({"move", "click", "double_click", "drag", "scroll", "hold"})
VALID_MODIFIERS = frozenset({"ctrl", "shift", "alt", "space"})
CAPTURE_LIFETIME_SECONDS = 90
MAX_DRAG_MS = 6000
MAX_DRAG_STEPS = 160
MAX_SCROLL_TICKS = 12
MAX_CAPTURE_PIXELS = 12_000_000


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def absolute(self, x: int, y: int) -> tuple[int, int]:
        if not self.in_bounds(x, y):
            raise ValueError(f"Relative point ({x}, {y}) is outside window {self.width}x{self.height}")
        return (self.left + x, self.top + y)


@dataclass(frozen=True)
class CaptureTicket:
    token: str
    window_id: str
    rect: Rect
    created: float
    method: str


class CaptureRegistry:
    def __init__(self, ttl: int = CAPTURE_LIFETIME_SECONDS):
        self.ttl = ttl
        self._tickets: dict[str, CaptureTicket] = {}

    def issue(self, window_id: str, rect: Rect, method: str, now: float | None = None) -> CaptureTicket:
        moment = time.monotonic() if now is None else now
        self._tickets = {k: v for k, v in self._tickets.items() if moment - v.created < self.ttl}
        ticket = CaptureTicket(uuid.uuid4().hex, window_id, rect, moment, method)
        self._tickets[ticket.token] = ticket
        if len(self._tickets) > 32:
            oldest = min(self._tickets.values(), key=lambda v: v.created).token
            self._tickets.pop(oldest, None)
        return ticket

    def verify(self, token: str, window_id: str, rect: Rect, now: float | None = None) -> CaptureTicket:
        moment = time.monotonic() if now is None else now
        ticket = self._tickets.get(token)
        if ticket is None:
            raise ValueError("Unknown or already used capture_id. Capture the window again.")
        if moment - ticket.created >= self.ttl:
            self._tickets.pop(token, None)
            raise ValueError("Screenshot expired. Capture the window again.")
        if window_id != ticket.window_id or rect != ticket.rect:
            raise ValueError("Window identity or position changed since screenshot. Capture again.")
        return ticket

    def consume(self, token: str) -> None:
        self._tickets.pop(token, None)


def normalize_allowlist(values: object) -> frozenset[str]:
    if not isinstance(values, list) or not values:
        raise ValueError("allow_processes must be a nonempty JSON array")
    result = set()
    for raw in values:
        if not isinstance(raw, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", raw):
            raise ValueError(f"Unsafe process name: {raw!r}")
        name = raw.lower()
        if not name.endswith(".exe"):
            name += ".exe"
        result.add(name)
    return frozenset(result)


def parse_modifiers(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    parts = [x.strip().lower() for x in value.split("+")]
    if not parts or any(p not in VALID_MODIFIERS for p in parts) or len(set(parts)) != len(parts):
        raise ValueError("modifiers must be a unique '+' joined subset of ctrl,shift,alt,space")
    return tuple(parts)


def validate_mouse(action: str, button: str, duration_ms: int, steps: int,
                   wheel_ticks: int, wheel_axis: str, modifiers: str) -> tuple[str, ...]:
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unsupported mouse action {action}")
    if button not in VALID_BUTTONS:
        raise ValueError(f"Unsupported button {button}")
    if not 40 <= duration_ms <= MAX_DRAG_MS:
        raise ValueError(f"duration_ms must be 40..{MAX_DRAG_MS}")
    if not 2 <= steps <= MAX_DRAG_STEPS:
        raise ValueError(f"steps must be 2..{MAX_DRAG_STEPS}")
    if not -MAX_SCROLL_TICKS <= wheel_ticks <= MAX_SCROLL_TICKS or wheel_ticks == 0:
        raise ValueError(f"wheel_ticks must be nonzero and in ±{MAX_SCROLL_TICKS}")
    if wheel_axis not in {"vertical", "horizontal"}:
        raise ValueError("wheel_axis must be vertical or horizontal")
    if action in {"drag", "double_click", "hold"} and button not in {"left", "right", "middle"}:
        raise ValueError("drag/double_click/hold support left, right or middle only")
    return parse_modifiers(modifiers)


def drag_points(start: tuple[int, int], end: tuple[int, int], steps: int) -> list[tuple[int, int]]:
    if not 2 <= steps <= MAX_DRAG_STEPS:
        raise ValueError("Invalid drag steps")
    result = []
    for i in range(steps + 1):
        t = i / steps
        xy = (round(start[0] + (end[0] - start[0]) * t),
              round(start[1] + (end[1] - start[1]) * t))
        if not result or xy != result[-1]:
            result.append(xy)
    return result
