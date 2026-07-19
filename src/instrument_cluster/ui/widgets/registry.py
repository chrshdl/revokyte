"""Widget registry: the building blocks a custom dashboard spec can place.

Maps the spec's widget type ids to factories. Spec rects are **bounding
boxes** in the 1280x720 design space (what a browser builder naturally
produces); each factory converts to the coordinates its widget class
expects (most anchor on their center) and applies srect scaling.

``default_rect`` mirrors where the standard dashboard places the widget
(status-lights shift not applied) — it seeds the builder's palette and
documents each block's designed size.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..constants import LAP_WIDGET_HEIGHT, LAP_WIDGET_Y
from ..utils import srect
from .current_lap_time_widget import CurrentLapTimeWidget
from .delta_time_widget import DeltaTimeWidget
from .fastest_lap_time_widget import FastestLapTimeWidget
from .fuel_laps_widget import FuelLapsWidget
from .fuel_per_lap_widget import FuelPerLapWidget
from .gear_widget import GearWidget
from .lap_time_widget import LapTimeWidget
from .lap_widget import LapWidget
from .predicted_lap_time_widget import PredictedLapTimeWidget
from .rpm_widget import RpmWidget
from .speed_widget import SpeedWidget
from .tire_temp_widget import TireTempWidget
from .track_name_widget import TrackNameWidget

# Gap between the four tire cells, in design px (matches the standard
# dashboard's 2x2 arrangement).
_TIRE_GAP = 4


@dataclass(frozen=True)
class RegistryEntry:
    """One placeable building block."""

    factory: Callable[[tuple[int, int, int, int], float], list]
    default_rect: tuple[int, int, int, int]  # bounding box, design px
    required_feature: str | None = None
    # Whether the spec may recolor the value text (headers stay white).
    # Blocks whose color carries meaning (delta's sign, the tire heatmap,
    # the RPM band) are not colorable. Keep in sync with the browser
    # builder's block catalog.
    colorable: bool = False

    def build(
        self,
        bbox: tuple[int, int, int, int],
        border: bool | None = None,
        extra: dict | None = None,
        color: str | None = None,
    ) -> list:
        """Instantiate at the bounding box; typography scales with the
        rect relative to the block's designed size (uniform, so text
        never distorts even when the box's aspect ratio does). ``border``
        overrides the widget class's own default when not None; ``color``
        ("#RRGGBB") tints the value text of colorable blocks and is
        ignored otherwise; ``extra`` passes further constructor kwargs
        through (the thumbnail tool renders value-only masks with
        ``header_text=""``)."""
        _, _, dw, dh = self.default_rect
        scale = min(bbox[2] / dw, bbox[3] / dh)
        merged = {} if border is None else {"show_border": border}
        if color and self.colorable:
            rgb = _hex_rgb(color)
            if rgb is not None:
                merged["value_color"] = rgb
        if extra:
            merged.update(extra)
        return self.factory(tuple(bbox), scale, merged)


def _hex_rgb(color: str) -> tuple[int, int, int] | None:
    """``#RRGGBB`` -> rgb tuple; None on anything malformed — a bad
    color must cost the tint, not the widget."""
    if len(color) == 7 and color[0] == "#":
        try:
            return (
                int(color[1:3], 16),
                int(color[3:5], 16),
                int(color[5:7], 16),
            )
        except ValueError:
            pass
    return None


def _centered(cls):
    """Factory for a widget class anchoring on its center point."""

    def build(bbox, font_scale, extra):
        x, y, w, h = bbox
        return [
            cls(
                rect=srect(x + w // 2, y + h // 2, w, h),
                font_scale=font_scale,
                **extra,
            )
        ]

    return build


def _topleft(cls):
    def build(bbox, font_scale, extra):
        return [cls(rect=srect(*bbox), font_scale=font_scale, **extra)]

    return build


def _tire_grid(bbox, font_scale, extra):
    """2x2 tire-temp cells filling the bounding box, standard gap."""
    x, y, w, h = bbox
    cw = (w - _TIRE_GAP) // 2
    ch = (h - _TIRE_GAP) // 2
    cells = [
        (x, y, "front_left", "T  FL"),
        (x + cw + _TIRE_GAP, y, "front_right", "T  FR"),
        (x, y + ch + _TIRE_GAP, "rear_left", "T  RL"),
        (x + cw + _TIRE_GAP, y + ch + _TIRE_GAP, "rear_right", "T  RR"),
    ]
    return [
        TireTempWidget(
            rect=srect(cx, cy, cw, ch),
            wheel_attr=attr,
            header_text=header,
            font_scale=font_scale,
            **extra,
        )
        for cx, cy, attr, header in cells
    ]


# Bounding boxes derived from the standard dashboard layout (center
# anchors converted to top-left, shifts at zero).
REGISTRY: dict[str, RegistryEntry] = {
    "gear": RegistryEntry(
        _centered(GearWidget), (547, 272, 186, 232), colorable=True
    ),
    "speed": RegistryEntry(
        _centered(SpeedWidget), (530, 22, 220, 140), colorable=True
    ),
    "rpm": RegistryEntry(_centered(RpmWidget), (542, 149, 196, 74)),
    "fastest-lap": RegistryEntry(
        _centered(FastestLapTimeWidget), (10, 21, 352, 94), colorable=True
    ),
    "predicted-lap": RegistryEntry(
        _centered(PredictedLapTimeWidget), (10, 116, 352, 94), colorable=True
    ),
    "current-lap": RegistryEntry(
        _centered(CurrentLapTimeWidget), (10, 211, 352, 94), colorable=True
    ),
    "track-name": RegistryEntry(
        _centered(TrackNameWidget), (10, 407, 352, 94), colorable=True
    ),
    "lap-time": RegistryEntry(
        _centered(LapTimeWidget), (926, 404, 336, 100), colorable=True
    ),
    "delta": RegistryEntry(_centered(DeltaTimeWidget), (926, 233, 336, 150)),
    "lap-counter": RegistryEntry(
        _topleft(LapWidget), (1172, LAP_WIDGET_Y, 90, LAP_WIDGET_HEIGHT),
        colorable=True,
    ),
    "tire-temps": RegistryEntry(_tire_grid, (1014, 22, 248, 188)),
    "fuel-per-lap": RegistryEntry(
        _centered(FuelPerLapWidget), (10, 211, 175, 94), colorable=True
    ),
    "fuel-laps": RegistryEntry(
        _centered(FuelLapsWidget), (187, 211, 175, 94), colorable=True
    ),
}


def known_types() -> set[str]:
    return set(REGISTRY)


def build(
    type_id: str,
    bbox: tuple[int, int, int, int],
    border: bool | None = None,
    color: str | None = None,
) -> list:
    """Instantiate the widgets for one spec entry. KeyError on unknown."""
    return REGISTRY[type_id].build(bbox, border, color=color)
