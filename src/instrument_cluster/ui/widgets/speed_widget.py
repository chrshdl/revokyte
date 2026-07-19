from ...core.vehicle.vehicle_bus import VehicleBus
from ...telemetry.models import TelemetryFrame
from ..widgets import Widget


class SpeedWidget(Widget):
    """
    Panel with a header text and a centered dynamic value underneath.
    Redraws only when the dynamic value changes.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = "Speed",
        anchor: str = "center",
        header_margin: int = 8,
        font_value_size: int = 108,
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
        self.set_value(0)

    def set_value(self, value: int):
        speed_str = "0" if value is None else str(value)
        if speed_str != self._last_value_str:
            self._last_value_str = speed_str
            self._render_value(speed_str)  # unchanged
            self.dirty = 1

    def update(self, bus: VehicleBus, dt: float):
        frame: TelemetryFrame = bus.frame
        if frame is None:
            return

        flags = getattr(frame, "flags", None)
        car_on_track = bool(getattr(flags, "car_on_track", False))
        if car_on_track:
            v = int((getattr(frame, "car_speed", 0.0) or 0.0) * 3.6)
        else:
            v = 0
        self.set_value(v)
