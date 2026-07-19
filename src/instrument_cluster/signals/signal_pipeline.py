from ..config import Config, ConfigManager
from ..logger import Logger
from ..telemetry.mode import TelemetryMode
from ..signals.delta_signal import DeltaSignal
from ..signals.fuel_signal import FuelSignal
from ..signals.track_signal import TrackSignal
from ..telemetry.demo import DemoDeltaSignal, DemoFuelSignal
from ..telemetry.source import TelemetrySource


class SignalPipeline:
    """
    Data-acquisition layer: always runs in the main loop regardless of which
    UI state is on the stack. This ensures the delta calculator and track
    detector keep receiving frames even while settings menus are open.

    Lifecycle: start() when the dashboard enters, stop() when it exits.
    Between those two calls, update() is invoked every frame by main.py.
    """

    def __init__(self, cfg: Config | None = None):
        cfg = cfg or ConfigManager.get_config()
        self.logger = Logger(__class__.__name__).get()
        self._last_mode = TelemetryMode(cfg.telemetry_mode)

        self.track = TrackSignal()
        self._delta_map: dict = {
            TelemetryMode.DEMO: DemoDeltaSignal(),
            TelemetryMode.UDP: DeltaSignal(),
        }
        self.delta = self._delta_map[self._last_mode]
        self._fuel_map: dict = {
            TelemetryMode.DEMO: DemoFuelSignal(),
            TelemetryMode.UDP: FuelSignal(),
        }
        self.fuel = self._fuel_map[self._last_mode]
        self.telemetry = TelemetrySource(
            mode=self._last_mode,
            host=cfg.udp_host,
            port=cfg.udp_port,
        )
        self._active = False

    def start(self) -> None:
        self.telemetry.start()
        self._active = True

    def stop(self) -> None:
        self._active = False
        self.track.stop()
        self.telemetry.stop()

    def sync_mode(self) -> None:
        """Apply a telemetry-mode change from config (call on dashboard resume)."""
        cfg = ConfigManager.get_config()
        desired = TelemetryMode(cfg.telemetry_mode)
        if desired == self._last_mode:
            return
        try:
            self.telemetry.switch_mode(desired)
            self.delta = self._delta_map[desired]
            self.fuel = self._fuel_map[desired]
            self._last_mode = desired
            self.logger.info(f"Telemetry mode switched to {desired.name}")
        except Exception as e:
            self.logger.error(f"Failed to switch telemetry mode: {e}")

    def update(self, bus, dt: float) -> None:
        if not self._active:
            return

        try:
            raw = self.telemetry.latest()
            if raw:
                bus.update_frame(raw)
        except Exception:
            pass

        if bus.frame is None:
            return

        try:
            bus.merge_signals(self.track.update(bus.frame, bus.signals))
            bus.merge_signals(self.delta.update(bus.frame, bus.signals, dt))
            bus.merge_signals(self.fuel.update(bus.frame, bus.signals, dt))
        except Exception as e:
            self.logger.warning(f"Signal processing error: {e}")
