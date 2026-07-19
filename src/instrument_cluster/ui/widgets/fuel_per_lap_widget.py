from ...core.vehicle.vehicle_bus import VehicleBus
from ...signals.signal_keys import SignalKey
from ..utils import FontFamily
from ..widgets import Widget

PLACEHOLDER = "--.-"


class FuelPerLapWidget(Widget):
    """
    Panel with a header text and a centered dynamic value underneath.
    Shows the fuel used so far in the current lap (GT7 gas units): 0.0 at
    the start/finish crossing, refreshed every few seconds by FuelSignal.
    Redraws only when the dynamic value changes.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = "Lap  Fuel",
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

        self.set_value(None)
        self.visible = 1
        self.dirty = 2

    def set_value(self, value: float | None):
        value_str = self._format(value)

        if value_str != self._last_value_str:
            self._last_value_str = value_str
            self._render_value(value_str)
            self.dirty = 1

    @staticmethod
    def _format(value: float | None) -> str:
        return f"{value:.2f}" if value is not None else PLACEHOLDER

    def update(self, bus: VehicleBus, dt: float):
        if bus.frame is None:
            return

        self.set_value(bus.signals.get(SignalKey.FUEL_USED_CURRENT_LAP))
