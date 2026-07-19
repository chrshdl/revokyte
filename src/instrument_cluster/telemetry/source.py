from .mode import TelemetryMode
from .demo import DemoReader
from .reader_protocol import TelemetryReaderProtocol
from .udp_jsonl import UdpJsonlReader


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
    ):
        if mode is None:
            mode = TelemetryMode.DEMO
        elif isinstance(mode, str):
            mode = TelemetryMode(mode)

        self._mode = mode
        self._host = host
        self._port = port

        # cached readers
        self._demo_reader: DemoReader | None = None
        self._udp_reader: UdpJsonlReader | None = None

        # active reader
        self._active_reader: TelemetryReaderProtocol = self._get_or_create_reader(mode)

    def _get_or_create_reader(self, mode: TelemetryMode) -> TelemetryReaderProtocol:
        """Get cached reader or create new one for the given mode."""
        if mode == TelemetryMode.UDP:
            if self._udp_reader is None:
                self._udp_reader = UdpJsonlReader(host=self._host, port=self._port)
            return self._udp_reader
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

        # Discard the stopped UDP reader; stop() joins its thread, but the instance
        # is no longer restartable — start() would spawn a second thread on stale state.
        if self._mode == TelemetryMode.UDP:
            self._udp_reader = None

        self._mode = new_mode
        self._active_reader = self._get_or_create_reader(new_mode)

        self.start()

    @property
    def mode(self) -> TelemetryMode:
        """Current telemetry mode."""
        return self._mode
