"""Finite physical input transactions; testable without loading Win32.

The adapter checks stop, identity, geometry, DPI and foreground. This class
checks the actual cursor and user-held keys and owns only successful downs.
"""
from __future__ import annotations

import time
from .policy import drag_points


class Transaction:
    def __init__(self, adapter, win):
        self.a, self.win = adapter, win
        self.owned = []
        self.pending_release = set()
        self.pointer = adapter.cursor()
        self.guard(foreground=False)
        adapter.activate(win)
        self.guard()

    def guard(self, *, foreground=True, hit=False):
        self.a.check(self.win, foreground=foreground)
        if self.a.cursor() != self.pointer:
            raise InterruptedError("Cursor changed/clamped or owner intervened; input aborted")
        owned_codes = set().union(*(self.a.code(kind, value) for kind, value in self.owned))
        if self.a.held_inputs() - owned_codes - self.pending_release:
            raise InterruptedError("Owner-held key/button detected; input aborted without releasing it")
        if hit:
            self.a.verify_hit(self.win, *self.pointer)
        if self.a.cursor() != self.pointer:
            raise InterruptedError("Owner moved the cursor during target verification")
        # The adapter rechecks identity/focus/stop after the hit query as well.
        self.a.check(self.win, foreground=foreground)

    def move(self, point):
        self.guard()
        self.a.position(*point)
        self.pointer = point
        self.guard(hit=True)

    def down(self, kind, value, *, hit=False):
        self.guard(hit=hit)
        self.a.emit(kind, value, True)
        self.owned.append((kind, value))

    def up(self, kind, value, *, hit=False):
        self.guard(hit=hit)
        self.a.emit(kind, value, False)
        self.owned.remove((kind, value))
        # SendInput inserts events; asynchronous key state may lag the key-up.
        # Wait before another effect, without repeating an already sent release.
        self.pending_release = self.a.code(kind, value)
        deadline = time.monotonic() + 0.15
        try:
            while True:
                self.guard(hit=hit)
                if not self.a.held_inputs() & self.pending_release:
                    return
                if time.monotonic() >= deadline:
                    raise InterruptedError("Released input state did not settle; owner may be holding the same key/button")
                self.a.wait(0.01)
        finally:
            self.pending_release = set()

    def wait(self, seconds, *, hit=False):
        end = time.monotonic() + seconds
        while True:
            self.guard(hit=hit)
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            self.a.wait(min(0.01, remaining))

    def cleanup(self):
        failed = []
        for kind, value in reversed(self.owned):
            try:
                self.a.emit(kind, value, False)
            except Exception:
                failed.append((kind, value))
        self.owned = list(reversed(failed))
        if failed:
            raise RuntimeError("Owned input release failed; use local emergency release and inspect desktop")


def mouse(adapter, win, action, button, x, y, end_x, end_y,
          duration_ms, steps, wheel_ticks, wheel_axis, modifiers):
    start, end = win.rect.absolute(x, y), win.rect.absolute(end_x, end_y)
    tx = Transaction(adapter, win)
    try:
        tx.move(start)
        for mod in modifiers:
            tx.down("key", adapter.key_codes[mod], hit=True)
        if action in {"click", "double_click"}:
            for i in range(2 if action == "double_click" else 1):
                if i:
                    tx.wait(0.06, hit=True)
                tx.down("button", button, hit=True)
                tx.wait(0.04, hit=True)
                tx.up("button", button, hit=True)
        elif action in {"drag", "hold"}:
            tx.down("button", button, hit=True)
            if action == "drag":
                points = drag_points(start, end, steps)
                for point in points[1:]:
                    tx.move(point)
                    tx.wait(duration_ms / 1000 / (len(points) - 1), hit=True)
            else:
                tx.wait(duration_ms / 1000, hit=True)
            tx.up("button", button, hit=True)
        elif action == "scroll":
            tx.guard(hit=True)
            adapter.wheel(wheel_axis, wheel_ticks * 120)
        elif action != "move":
            raise ValueError("Unexpected action")
        for mod in reversed(modifiers):
            tx.up("key", adapter.key_codes[mod], hit=True)
        tx.guard(hit=True)
    finally:
        tx.cleanup()


def keys(adapter, win, names):
    tx = Transaction(adapter, win)
    try:
        for name in names:
            tx.down("key", adapter.key_codes[name])
        tx.wait(0.06)
        for name in reversed(names):
            tx.up("key", adapter.key_codes[name])
        tx.guard()
    finally:
        tx.cleanup()


def text(adapter, win, value, replace_all=False):
    encoded = value.encode("utf-16-le")
    tx = Transaction(adapter, win)
    try:
        if replace_all:
            tx.down("key", adapter.key_codes["ctrl"])
            tx.down("key", adapter.key_codes["a"])
            tx.up("key", adapter.key_codes["a"])
            tx.up("key", adapter.key_codes["ctrl"])
            tx.wait(0.04)
        for offset in range(0, len(encoded), 2):
            unit = int.from_bytes(encoded[offset:offset + 2], "little")
            tx.down("unicode", unit)
            tx.up("unicode", unit)
        tx.guard()
    finally:
        tx.cleanup()
