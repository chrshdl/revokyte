from typing import Callable

from ..logger import Logger
from .mode import TelemetryMode
from .demo import DemoReader
from .reader_protocol import TelemetryReaderProtocol
from .udp_jsonl import UdpJsonlReader


class _InertReader:
    """Stands in when a direct reader can't be built: it never publishes a
    frame, so the dashboard honestly shows no data instead of demo motion."""

    def start(self) -> None:
        pass

    def latest(self) -> None:
        return None

    def stop(self) -> None:
        pass


class TelemetrySource:
    """
    Manages telemetry readers with mode switching support.
    Caches reader instances to avoid recreation when switching modes.
    """

    def __init__(
        self,
        mode: TelemetryMode | str | None = None,
        host: str = "127.0.0.1",
        port: int = 5600,
        direct_reader_factory: Callable[[], TelemetryReaderProtocol] | None = None,
    ):
        if mode is None:
            mode = TelemetryMode.DEMO
        elif isinstance(mode, str):
            mode = TelemetryMode(mode)

        self.logger = Logger(__class__.__name__).get()
        self._mode = mode
        self._host = host
        self._port = port
        # Builds the in-process reader for the configured feed (desktop
        # DIRECT mode); reads live config at call time, so recreating the
        # reader picks up an address change.
        self._direct_reader_factory = direct_reader_factory

        # cached readers
        self._demo_reader: DemoReader | None = None
        self._udp_reader: UdpJsonlReader | None = None
        self._direct_reader: TelemetryReaderProtocol | None = None

        # active reader
        self._active_reader: TelemetryReaderProtocol = self._get_or_create_reader(mode)

    def _create_direct_reader(self) -> TelemetryReaderProtocol:
        try:
            if self._direct_reader_factory is None:
                raise RuntimeError("no direct reader factory configured")
            return self._direct_reader_factory()
        except Exception as e:
            self.logger.error(f"Cannot build direct telemetry reader: {e}")
            return _InertReader()

    def _get_or_create_reader(self, mode: TelemetryMode) -> TelemetryReaderProtocol:
        """Get cached reader or create new one for the given mode."""
        if mode == TelemetryMode.UDP:
            if self._udp_reader is None:
                self._udp_reader = UdpJsonlReader(host=self._host, port=self._port)
            return self._udp_reader
        elif mode == TelemetryMode.DIRECT:
            if self._direct_reader is None:
                self._direct_reader = self._create_direct_reader()
            return self._direct_reader
        else:
            if self._demo_reader is None:
                self._demo_reader = DemoReader()
            return self._demo_reader

    @property
    def reader(self):
        """Current active reader."""
        return self._active_reader

    def start(self) -> None:
        """Start the active reader."""
        self._active_reader.start()

    def latest(self):
        """Get the latest telemetry frame from the active reader."""
        return self._active_reader.latest()

    def stop(self) -> None:
        """Stop the active reader."""
        self._active_reader.stop()

    def switch_mode(self, new_mode: TelemetryMode) -> None:
        """
        Switch to a different telemetry mode.
        Stops the current reader and starts the new one.
        Reuses cached reader instances.
        """
        if new_mode == self._mode:
            return

        self.stop()

        # Discard stopped network readers; stop() joins their threads, but the
        # instances are no longer restartable — start() would spawn a second
        # thread on stale state.
        if self._mode == TelemetryMode.UDP:
            self._udp_reader = None
        elif self._mode == TelemetryMode.DIRECT:
            self._direct_reader = None

        self._mode = new_mode
        self._active_reader = self._get_or_create_reader(new_mode)

        self.start()

    def refresh_direct(self) -> None:
        """Rebuild the direct reader in place (its target address changed).

        No-op unless DIRECT is the active mode — the factory reads live
        config, so a fresh reader picks up the new address.
        """
        if self._mode != TelemetryMode.DIRECT:
            return
        self.stop()
        self._direct_reader = None
        self._active_reader = self._get_or_create_reader(self._mode)
        self.start()

    @property
    def mode(self) -> TelemetryMode:
        """Current telemetry mode."""
        return self._mode
