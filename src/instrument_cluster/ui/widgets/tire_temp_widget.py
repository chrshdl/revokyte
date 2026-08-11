from __future__ import annotations

from ...core.vehicle.vehicle_bus import VehicleBus
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...telemetry.models import TelemetryFrame
from ..colors import Color
from ..utils import FontFamily
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
        font_value_family: FontFamily | None = None,
        show_border: bool = True,
        antialias: bool = True,
        text_color: tuple[int, int, int] | None = None,
        bg_gradient_top: tuple[int, int, int] | None = None,
        bg_gradient_bottom: tuple[int, int, int] | None = None,
        font_scale: float = 1.0,
        header_font_size: int | None = None,
    ):
        if header_text is None:
            header_text = wheel_attr
        # Resolve the heat-gradient defaults at construction so palette
        # overrides (skin editor) reach a rebuilt gauge; None must not fall
        # through to the base class, where it means "no gradient".
        if bg_gradient_top is None:
            bg_gradient_top = Color.DARK_GREY.rgb()
        if bg_gradient_bottom is None:
            bg_gradient_bottom = Color.RPM_RED.rgb()

        super().__init__(
            rect=rect,
            header_text=header_text,
            anchor=anchor,
            font_value_size=font_value_size,
            font_value_family=font_value_family,
            text_color=text_color,
            show_border=show_border,
            antialias=antialias,
            bg_gradient_top=bg_gradient_top,
            bg_gradient_bottom=bg_gradient_bottom,
            font_scale=font_scale,
            header_font_size=header_font_size,
        )
        self.wheel_attr = wheel_attr
        self.set_value(-1)

    def set_value(self, value: int):
        if value == self._last_raw_value and self._last_value_str is not None:
            return
        self._last_raw_value = value

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
