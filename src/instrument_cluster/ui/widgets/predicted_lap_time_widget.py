
from ...core.vehicle.vehicle_bus import VehicleBus
from ...signals.signal_keys import SignalKey
from ...telemetry.models import TelemetryFrame
from ..constants import LAP_DEFAULT_VALUE
from ..utils import FontFamily
from ..widgets import Widget


class PredictedLapTimeWidget(Widget):
    """
    Panel with a header text and a centered dynamic value underneath.
    Redraws only when the dynamic value changes.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = "Predicted   Lap",
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

        self.set_value(LAP_DEFAULT_VALUE)
        self.visible = 1
        self.dirty = 2

    def set_value(self, time: float | None = None):
        time_str = self.format_mm_ss_hh(time) if time is not None else ""

        if time_str != self._last_value_str:
            self._last_value_str = time_str
            self._render_value(time_str)
            self.dirty = 1

    def format_mm_ss_hh(self, seconds: float) -> str:
        if seconds is None:
            return ""
        # to avoid rendering negative time if delta is wildly huge
        seconds = max(0.0, seconds)

        cs = int(seconds * 100)
        m = cs // 6000
        s = (cs // 100) % 60
        hh = cs % 100
        return f"{m:02d}:{s:02d}.{hh:02d}"

    def reset(self) -> None:
        self.set_value(LAP_DEFAULT_VALUE)

    def update(self, bus: VehicleBus, dt: float):
        frame: TelemetryFrame = bus.frame
        if frame is None:
            return

        if not frame.lap_count:
            self.reset()
            return

        delta = bus.signals.get(SignalKey.DELTA_DIFF_STABLE)
        if delta is None:
            self.set_value(0)
            return

        # Use the calculator's own reference lap time so both sides of the
        # addition are on the same pygame-clock timing base. GT7's
        # best_lap_time / last_lap_time uses a different clock and can drift
        # by ~2 s over a 70-80 s lap, causing a systematic prediction error.
        ref_s = bus.signals.get(SignalKey.DELTA_REF_LAP_TIME)
        if not ref_s:
            self.set_value(0)
            return

        self.set_value(ref_s + delta)
