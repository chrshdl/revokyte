from ..config import Config, ConfigManager
from ..logger import Logger
from ..telemetry.mode import TelemetryMode
from ..signals.delta_signal import DeltaSignal
from ..signals.fuel_signal import FuelSignal
from ..signals.link_signal import LinkSignal
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
        # DIRECT is live telemetry like UDP, just read in-process — it gets
        # the real signal processors, not the demo ones.
        self._delta_map: dict = {
            TelemetryMode.DEMO: DemoDeltaSignal(),
            TelemetryMode.UDP: DeltaSignal(),
            TelemetryMode.DIRECT: DeltaSignal(),
        }
        self.delta = self._delta_map[self._last_mode]
        self._fuel_map: dict = {
            TelemetryMode.DEMO: DemoFuelSignal(),
            TelemetryMode.UDP: FuelSignal(),
            TelemetryMode.DIRECT: FuelSignal(),
        }
        self.fuel = self._fuel_map[self._last_mode]
        # Link supervision is mode-independent: every source can go quiet.
        self.link = LinkSignal()
        self.telemetry = TelemetrySource(
            mode=self._last_mode,
            host=cfg.udp_host,
            port=cfg.udp_port,
            direct_reader_factory=self._make_direct_reader,
        )
        self._last_direct_host = cfg.direct_host
        self._last_udp_host = cfg.udp_host
        self._active = False
        # Set by a source switch; consumed by the next update(), which is
        # where the bus is in hand (main loop).
        self._pending_reset = False

    def _begin_session(self, mode: TelemetryMode) -> None:
        """Fresh enrichment state for a new telemetry source/session.

        A different source (or a different console at the same mode) is a
        different session: the live processors and the track lock restart
        from scratch, and the next update() clears the bus so the old
        source's last values never linger on the gauges.
        """
        if mode != TelemetryMode.DEMO:
            self._delta_map[mode] = DeltaSignal()
            self._fuel_map[mode] = FuelSignal()
        self.track = TrackSignal()
        self.delta = self._delta_map[mode]
        self.fuel = self._fuel_map[mode]
        self.link.reset()
        self._pending_reset = True

    @staticmethod
    def _make_direct_reader():
        """Build the in-process reader for the configured feed (desktop
        DIRECT mode). Reads live config so a rebuilt reader picks up the
        current feed selection and console address."""
        from ..addons.feeds import feed_by_id

        cfg = ConfigManager.get_config()
        descriptor = feed_by_id(cfg.telemetry_feed)
        if descriptor is None or descriptor.direct_reader is None:
            raise RuntimeError(
                f"feed {cfg.telemetry_feed!r} has no in-process reader"
            )
        if not cfg.direct_host:
            raise RuntimeError("no console IP configured for direct telemetry")
        return descriptor.direct_reader(cfg.direct_host)

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
            # Same mode, but the direct reader's console address changed
            # (user re-entered an IP): rebuild the reader against it.
            if (
                desired == TelemetryMode.DIRECT
                and cfg.direct_host != self._last_direct_host
            ):
                self._last_direct_host = cfg.direct_host
                self.telemetry.refresh_direct()
                self._begin_session(desired)
            # Same mode, but the UDP bind host changed — the agent pairing
            # flow flips 127.0.0.1 → 0.0.0.0 so a game-PC sender can reach
            # the cluster. Without this rebind the reader kept its
            # boot-time loopback bind until the next reboot, and a freshly
            # paired agent streamed at a cluster that never heard it.
            if (
                desired == TelemetryMode.UDP
                and cfg.udp_host != self._last_udp_host
            ):
                self._last_udp_host = cfg.udp_host
                self.telemetry.set_udp_host(cfg.udp_host)
                self._begin_session(desired)
            return
        try:
            # The bind host may have changed together with the mode (the
            # pairing flow sets both): hand the source the current host
            # before the switch builds the reader from it.
            if desired == TelemetryMode.UDP:
                self._last_udp_host = cfg.udp_host
                self.telemetry.set_udp_host(cfg.udp_host)
            self.telemetry.switch_mode(desired)
            self._begin_session(desired)
            self._last_mode = desired
            self._last_direct_host = cfg.direct_host
            self.logger.info(f"Telemetry mode switched to {desired.name}")
        except Exception as e:
            self.logger.error(f"Failed to switch telemetry mode: {e}")

    def update(self, bus, dt: float) -> None:
        if not self._active:
            return

        if self._pending_reset:
            self._pending_reset = False
            bus.reset_telemetry()

        try:
            raw = self.telemetry.latest()
            if raw:
                bus.update_frame(raw)
        except Exception:
            pass

        # Link supervision runs before the no-frame guard below: a reader
        # that has never produced a frame (inert direct reader, feed not yet
        # connected) is precisely the case the driver needs told about, and
        # returning early would leave the dash silently blank instead.
        bus.merge_signals(self.link.update(bus.frame, bus.signals, dt))

        if bus.frame is None:
            return

        try:
            bus.merge_signals(self.track.update(bus.frame, bus.signals))
            bus.merge_signals(self.delta.update(bus.frame, bus.signals, dt))
            bus.merge_signals(self.fuel.update(bus.frame, bus.signals, dt))
        except Exception as e:
            self.logger.warning(f"Signal processing error: {e}")
