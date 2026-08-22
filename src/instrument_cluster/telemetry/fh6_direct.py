"""In-process Forza Horizon 6 telemetry for the desktop build.

Drives an :class:`fh6.Feed` (the same library the appliance's proxy program
wraps) on a background thread and republishes each decoded packet as a
:class:`TelemetryFrame` — the proxy's data path minus the separate process
and the NDJSON round-trip. Referenced only by the forza-horizon-6 entry in
``addons/feeds.py``; nothing else in the app knows this module exists.

FH6 is a listener, not something this device dials: the game pushes to
whatever address and port is configured *in-game* (see
``ListenerSetupState``), and ``fh6.Feed`` only needs a local port to bind.
The ``ip`` this class is constructed with — required so it fits the same
``Callable[[str], TelemetryReaderProtocol]`` shape every direct reader does,
and so ``SignalPipeline._make_direct_reader``'s "no console IP configured"
guard is satisfied — is therefore unused.

``fh6`` is an optional dependency (the ``pc`` extra): the import is deferred
to :meth:`Fh6DirectReader.start`, and a build without it degrades to an
inert reader with an error in the log.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from ..logger import Logger
from .models import Bounds, Flags, TelemetryFrame, Vector

# Kept in sync with fh6.model.frame's constant of the same name.
_REV_WARNING_FRACTION = 0.95


def _map_gear(raw_gear: int) -> int:
    """Mirrors ``fh6.model.frame.map_gear`` — kept as a local duplicate (not
    an import) so this mapper, like ``gt7_direct.packet_to_frame`` and
    ``acc_direct.acc_frame_to_frame``, is testable without the optional
    dependency installed.

    UNCONFIRMED placeholder: see forza-horizon-6's CLAUDE.md "Field-confirmed
    protocol details" section. If that mapping is corrected there, mirror
    the fix here too.
    """
    if raw_gear <= 0:
        return 0
    if raw_gear == 1:
        return -1
    return raw_gear - 1


def _lap_ms(seconds: float) -> int | None:
    """FH6 reports lap times in seconds, with 0.0 meaning "not applicable"."""
    return None if seconds <= 0.0 else round(seconds * 1000)


def packet_to_frame(packet) -> TelemetryFrame:
    """Map an fh6 ``Packet`` (or anything shaped like one) to the app's
    ``TelemetryFrame`` schema.

    Mirrors ``fh6.model.frame.build_frame()`` field for field, so the
    direct-reading and proxy-installed paths agree. ``wheels``/
    ``gear_ratios``/``engine`` are never passed at all: FH6 has no data for
    them, and unlike the NDJSON path (where the key is simply omitted from
    the dict) an explicit ``None`` here would fail pydantic validation
    rather than fall back to the schema's default.
    """
    kwargs: dict = dict(
        received_time=packet.received_time,
        car_id=packet.car_ordinal,
        car_speed=packet.speed,
        engine_rpm=packet.current_engine_rpm,
        current_gear=_map_gear(packet.gear),
        throttle=round(packet.accel / 255.0, 4),
        brake=round(packet.brake / 255.0, 4),
        gas_level=packet.fuel,
        gas_capacity=1.0,
        lap_count=packet.lap_number,
        best_lap_time=_lap_ms(packet.best_lap),
        last_lap_time=_lap_ms(packet.last_lap),
        current_lap_time=_lap_ms(packet.current_lap),
        flags=Flags(car_on_track=packet.is_race_on, paused=not packet.is_race_on),
        position=Vector(
            x=packet.position.x, y=packet.position.y, z=packet.position.z
        ),
    )
    max_rpm = packet.engine_max_rpm
    if max_rpm > 0:
        kwargs["rpm_alert"] = Bounds(min=max_rpm * _REV_WARNING_FRACTION, max=max_rpm)
    return TelemetryFrame(**kwargs)


class Fh6DirectReader:
    """TelemetryReaderProtocol over an ``fh6.Feed``.

    Like ``Gt7DirectReader``, an instance is not restartable after
    ``stop()`` — ``TelemetrySource`` discards it on every mode switch or
    reconfigure. A failed ``start()`` (library missing, the feed's port
    already bound) leaves the reader inert: ``latest()`` keeps returning
    ``None`` and the dashboard honestly shows no data.
    """

    def __init__(
        self,
        _ip: str,
        feed_factory: Callable[[], object] | None = None,
    ):
        self.logger = Logger(__class__.__name__).get()
        self._feed_factory = feed_factory
        self._feed = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._latest: TelemetryFrame | None = None
        self._dropped = 0
        self._last_drop_log = 0.0

    def start(self) -> None:
        if self._running:
            return

        factory = self._feed_factory
        if factory is None:
            try:
                from fh6 import Feed
            except ImportError as e:
                self.logger.error(
                    f"forza-horizon-6 is not installed; direct FH6 "
                    f"telemetry is unavailable: {e}"
                )
                return
            factory = Feed

        try:
            feed = factory()
            feed.start()
        except OSError as e:
            self.logger.error(f"Could not open direct FH6 telemetry feed: {e}")
            return

        self._feed = feed
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.logger.info("Direct FH6 telemetry started")

    def _run(self) -> None:
        feed = self._feed
        while self._running:
            packet = feed.get_latest(timeout=1.0)
            if packet is None:
                continue
            try:
                self._latest = packet_to_frame(packet)
            except Exception as e:
                # One bad packet must not kill the reader, but total loss
                # must not be silent either (see UdpJsonlReader).
                self._dropped += 1
                now = time.monotonic()
                if now - self._last_drop_log >= 5.0:
                    self._last_drop_log = now
                    self.logger.warning(
                        f"Dropped {self._dropped} unmappable FH6 "
                        f"packet(s) so far; last error: {e}"
                    )

    def latest(self) -> TelemetryFrame | None:
        return self._latest

    def stop(self) -> None:
        self._running = False
        if self._feed is not None:
            try:
                self._feed.close()
            finally:
                self._feed = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
