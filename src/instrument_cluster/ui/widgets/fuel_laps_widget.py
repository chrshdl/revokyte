from ...core.vehicle.vehicle_bus import VehicleBus
from ...signals.signal_keys import SignalKey
from ..colors import Color
from ..utils import FontFamily
from ..widgets import Widget

PLACEHOLDER = "--.-"

# An implausibly large estimate stays two digits wide.
MAX_DISPLAY_LAPS = 99.9

# Low-fuel warning thresholds (estimated laps remaining).
WARN_LAPS = 3.0
CRITICAL_LAPS = 1.0


class FuelLapsWidget(Widget):
    """
    Panel with a header text and a centered dynamic value underneath.
    Shows the estimated laps remaining on the current fuel level, based on
    a rolling average of recent laps' consumption.
    Redraws only when the dynamic value changes.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = "Fuel  Remain",
        anchor: str = "center",
        font_value_size: int = 48,
        font_value_family: FontFamily = FontFamily.D_DIN_EXP,
        show_border: bool = True,
        antialias: bool = True,
        font_scale: float = 1.0,
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
            value_color=value_color,
        )

        self._last_color = None
        self.set_value(None)
        self.visible = 1
        self.dirty = 2

    def set_value(self, value: float | None):
        if value == self._last_raw_value and self._last_value_str is not None:
            return
        self._last_raw_value = value

        value_str = self._format(value)
        color = self._warning_color(value)

        if value_str != self._last_value_str or color != self._last_color:
            self._last_value_str = value_str
            self._last_color = color
            self._render_value(value_str, color)
            self.dirty = 1

    @staticmethod
    def _format(value: float | None) -> str:
        if value is None:
            return PLACEHOLDER
        return f"{min(value, MAX_DISPLAY_LAPS):.1f}"

    def _warning_color(self, value: float | None) -> tuple[int, int, int]:
        if value is None:
            return self.text_color
        if value < CRITICAL_LAPS:
            return Color.LIGHT_RED.rgb()
        if value < WARN_LAPS:
            return Color.YELLOW.rgb()
        return self.text_color

    def update(self, bus: VehicleBus, dt: float):
        if bus.frame is None:
            return

        self.set_value(bus.signals.get(SignalKey.FUEL_LAPS_REMAINING))
