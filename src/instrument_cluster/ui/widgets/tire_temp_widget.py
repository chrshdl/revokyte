from ...core.vehicle.vehicle_bus import VehicleBus
from ...telemetry.models import TelemetryFrame
from ..colors import Color
from ..widgets import Widget


class TireTempWidget(Widget):
    """
    Panel with a header text and a centered dynamic value underneath.
    Redraws only when the dynamic value changes.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        wheel_attr: str = "front_left",
        header_text: str | None = None,
        anchor: str = "topleft",
        font_value_size: int = 44,
        show_border: bool = True,
        antialias: bool = True,
        text_color: tuple[int, int, int] = Color.WHITE.rgb(),
        bg_gradient_top: tuple[int, int, int] | None = Color.DARK_GREY.rgb(),
        bg_gradient_bottom: tuple[int, int, int] | None = Color.RPM_RED.rgb(),
        font_scale: float = 1.0,
    ):
        if header_text is None:
            header_text = wheel_attr

        super().__init__(
            rect=rect,
            header_text=header_text,
            anchor=anchor,
            font_value_size=font_value_size,
            text_color=text_color,
            show_border=show_border,
            antialias=antialias,
            bg_gradient_top=bg_gradient_top,
            bg_gradient_bottom=bg_gradient_bottom,
            font_scale=font_scale,
        )
        self.wheel_attr = wheel_attr
        self.set_value(-1)

    def set_value(self, value: int):
        temp_str = str(value)

        if temp_str != self._last_value_str:
            self._last_value_str = temp_str
            self._render_value(temp_str)
            self.dirty = 1

    def update(self, bus: VehicleBus, dt: float):
        frame: TelemetryFrame = bus.frame
        if frame is None:
            return

        wheels = getattr(frame, "wheels", None)
        wheel = getattr(wheels, self.wheel_attr, None)
        temp = getattr(wheel, "temperature", 0) if wheel is not None else 0
        self.set_value(int(temp) or 0)
