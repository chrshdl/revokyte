from __future__ import annotations

from ...core.vehicle.vehicle_bus import VehicleBus
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...telemetry.models import TelemetryFrame
from ..utils import FontFamily
from ..widgets import Widget


class LapWidget(Widget):
    """
    Panel with a header text and a centered dynamic value underneath.
    Redraws only when the dynamic value changes.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = "Lap",
        anchor: str = "topleft",
        font_value_size: int = 44,
        font_value_family: FontFamily | None = None,
        show_border: bool = True,
        antialias: bool = True,
        font_scale: float = 1.0,
        header_font_size: int | None = None,
        value_color: tuple[int, int, int] | None = None,
    ):
        super().__init__(
            rect=rect,
            header_text=header_text,
            anchor=anchor,
            font_value_size=font_value_size,
            font_value_family=font_value_family,
            show_border=show_border,
            antialias=antialias,
            font_scale=font_scale,
            header_font_size=header_font_size,
            value_color=value_color,
        )

        self.set_value(-1)

    def set_value(self, value: int):
        lap_str = str(value)

        if lap_str != self._last_value_str:
            self._last_value_str = lap_str
            self._render_value(lap_str)
            self.dirty = 1

    def update(self, bus: VehicleBus, dt: float):
        frame: TelemetryFrame = bus.frame
        if frame is None:
            return

        flags = getattr(frame, "flags", None)
        car_on_track = bool(getattr(flags, "car_on_track", False))
        if car_on_track:
            lap = int(getattr(frame, "lap_count", 0) or 0)
        else:
            lap = 0
        self.set_value(lap)
