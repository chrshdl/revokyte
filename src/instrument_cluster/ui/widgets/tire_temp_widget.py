from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.vehicle.vehicle_bus import VehicleBus

if TYPE_CHECKING:
    from ...telemetry.models import TelemetryFrame
from ..colors import Color
from ..utils import FontFamily, arc_gradient
from ..widgets import Widget


class TireTempWidget(Widget):
    """
    Panel with a header text and a centered dynamic value underneath.
    Redraws only when the dynamic value changes.

    The background is a radial glow rather than the base class's vertical
    ramp: the lit end pools in the lower centre, behind the digits, and
    falls off towards every edge — darkest in the top corners, where the
    top and side shadows meet. Reading it as a soft inner shadow rather
    than a ramp is what frames the value the way the panel art does.
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
        from ..skins import active_skin

        d = active_skin().dashboard
        if bg_gradient_top is None:
            bg_gradient_top = Color[d.tire_gradient_top].rgb()
        if bg_gradient_bottom is None:
            bg_gradient_bottom = Color[d.tire_gradient_bottom].rgb()

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

    def _create_background_gradient(
        self,
        top_color: tuple[int, int, int] | None,
        bottom_color: tuple[int, int, int] | None,
    ):
        if top_color is None or bottom_color is None:
            return None
        return arc_gradient((self.w, self.h), top_color, bottom_color)
