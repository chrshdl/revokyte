from __future__ import annotations

from ...core.vehicle.vehicle_bus import VehicleBus
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...telemetry.models import TelemetryFrame
from ..widgets import Widget


class GearWidget(Widget):
    """
    Panel with a header text and a centered dynamic value underneath.
    Redraws only when the dynamic value changes.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = "Gear",
        anchor: str = "center",
        header_margin: int = 3,
        font_value_size: int = 264,
        show_border: bool = False,
        antialias: bool = True,
        font_scale: float = 1.0,
        value_color: tuple[int, int, int] | None = None,
    ):
        super().__init__(
            rect=rect,
            header_text=header_text,
            anchor=anchor,
            header_margin=header_margin,
            font_value_size=font_value_size,
            show_border=show_border,
            antialias=antialias,
            font_scale=font_scale,
            value_color=value_color,
        )
        self.set_value(-1)

    def set_value(self, value: int):
        if value == 0:
            gear_str = "R"
        elif value == -1:
            gear_str = "N"
        elif value == -2:
            gear_str = "P"
        else:
            gear_str = str(value)

        if gear_str != self._last_value_str:
            self._last_value_str = gear_str
            self._render_value(gear_str)
            self.dirty = 1

    def update(self, bus: VehicleBus, dt: float):
        frame: TelemetryFrame = bus.frame
        if frame is None:
            return

        flags = getattr(frame, "flags", None)
        car_on_track = bool(getattr(flags, "car_on_track", False))
        if car_on_track:
            gear = int(getattr(frame, "current_gear", 0) or 0)
        else:
            gear = -2  # P
        self.set_value(gear)
