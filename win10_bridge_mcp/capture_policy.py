"""Explicit screenshot targets and physical-pixel bounds; no desktop fallback."""
from dataclasses import dataclass
from .policy import Rect, MAX_CAPTURE_PIXELS

CAPTURE_MODES = frozenset({"window", "monitor", "virtual_desktop", "region"})


@dataclass(frozen=True)
class Display:
    id: str
    rect: Rect
    dpi_x: int
    dpi_y: int
    dpi_source: str = "reported"
    scale_percent: int = 100


@dataclass(frozen=True)
class DesktopLayout:
    displays: tuple[Display, ...]

    def __post_init__(self):
        if not self.displays or len(self.displays) > 64:
            raise ValueError("One to 64 active displays required")
        if len({d.id for d in self.displays}) != len(self.displays):
            raise ValueError("Duplicate monitor identity; inspect targets again")
        for display in self.displays:
            if display.rect.width <= 0 or display.rect.height <= 0 or min(display.dpi_x, display.dpi_y, display.scale_percent) <= 0:
                raise ValueError("Invalid monitor geometry/scale")

    @property
    def bounds(self):
        if not self.displays:
            raise ValueError("No active display")
        return Rect(min(d.rect.left for d in self.displays), min(d.rect.top for d in self.displays),
                    max(d.rect.right for d in self.displays), max(d.rect.bottom for d in self.displays))

    def describe(self):
        return {"coordinate_space": "physical_pixels", "virtual_desktop": rect_data(self.bounds),
                "monitors": [{"monitor_id": d.id, "rect": rect_data(d.rect),
                              "dpi": [d.dpi_x, d.dpi_y], "dpi_source": d.dpi_source,
                              "scale_percent": d.scale_percent} for d in self.displays]}


def rect_data(rect):
    return {"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height}


def validate_pixels(rect):
    if rect.width <= 0 or rect.height <= 0 or rect.width * rect.height > MAX_CAPTURE_PIXELS:
        raise ValueError(f"Capture must have positive dimensions and at most {MAX_CAPTURE_PIXELS} pixels")
    if any(not -2**31 <= p < 2**31 for p in (rect.left, rect.top, rect.right, rect.bottom)):
        raise ValueError("Capture coordinates exceed Win32 range")


def choose_region(mode, layout, *, monitor_id="", left=0, top=0, width=0, height=0):
    if mode == "monitor":
        if any((left, top, width, height)):
            raise ValueError("Monitor mode does not take a region")
        matches = [d for d in layout.displays if d.id == monitor_id]
        if len(matches) != 1:
            raise ValueError("Unknown monitor_id; inspect_capture_targets again")
        rect = matches[0].rect
    elif mode == "virtual_desktop":
        if monitor_id or any((left, top, width, height)):
            raise ValueError("Virtual desktop mode does not take monitor/region arguments")
        rect = layout.bounds
    elif mode == "region":
        if monitor_id:
            raise ValueError("Region uses absolute physical coordinates, not monitor_id")
        rect = Rect(left, top, left + width, top + height)
        bounds = layout.bounds
        if rect.left < bounds.left or rect.top < bounds.top or rect.right > bounds.right or rect.bottom > bounds.bottom:
            raise ValueError("Region is outside the virtual desktop bounds")
    else:
        raise ValueError("Select explicit monitor, virtual_desktop or region mode")
    validate_pixels(rect)
    return rect
