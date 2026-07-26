from ...core.vehicle.vehicle_bus import VehicleBus
from ...telemetry.models import TelemetryFrame
from ..constants import LAP_DEFAULT_VALUE
from ..utils import FontFamily
from ..widgets import Widget

# The lap clock ticks in milliseconds, so its raw value changes on every
# frame — hundredths at 60 Hz are unreadable anyway, so the *rendered*
# text refreshes at 10 Hz (the same idea as DeltaSignal's stable display).
_DISPLAY_REFRESH_S = 0.1


class CurrentLapTimeWidget(Widget):
    """
    Panel with a header text and a centered dynamic value underneath.
    Redraws only when the dynamic value changes.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = "Current   Lap",
        anchor: str = "center",
        font_value_size: int = 64,
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

        # Starts elapsed so the first live value paints without delay.
        self._refresh_elapsed = _DISPLAY_REFRESH_S
        self.set_value(LAP_DEFAULT_VALUE)
        self.visible = 1

    def set_value(self, time: float | None = None):
        time_str = self.format_mm_ss_hh(time) if time is not None else ""

        if time_str != self._last_value_str:
            self._last_value_str = time_str
            self._render_value(time_str)
            self.dirty = 1

    def format_mm_ss_hh(self, seconds: float) -> str:
        cs = max(0, int(seconds * 100))
        m = cs // 6000
        s = (cs // 100) % 60
        hh = cs % 100
        return f"{m:02d}:{s:02d}.{hh:02d}"

    def reset(self) -> None:
        # Re-arm so the first live value after a reset paints immediately.
        self._refresh_elapsed = _DISPLAY_REFRESH_S
        self.set_value(LAP_DEFAULT_VALUE)

    def update(self, bus: VehicleBus, dt: float):
        frame: TelemetryFrame = bus.frame
        if frame is None:
            return

        if not frame.lap_count:
            self.reset()
            return

        if frame.current_lap_time is None:
            self.reset()
            return

        self._refresh_elapsed += dt
        if self._refresh_elapsed < _DISPLAY_REFRESH_S:
            return
        self._refresh_elapsed = 0.0

        current_lap_time = float(frame.current_lap_time * 1e-3)
        self.set_value(current_lap_time)
