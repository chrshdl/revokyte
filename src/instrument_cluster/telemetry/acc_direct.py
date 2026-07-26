"""In-process ACC telemetry for the desktop build.

Drives an :class:`acc.Feed` (the same Broadcasting-API client the appliance's
ACC feed program wraps) on a background thread and republishes each
focused-car update as a :class:`TelemetryFrame` — the proxy's data path minus
the separate process and the NDJSON round-trip. Referenced only by the acc
entry in ``addons/feeds.py``; nothing else in the app knows this module
exists.

``acc-telemetry`` is an optional dependency (the ``pc`` extra): the import is
deferred to :meth:`AccDirectReader.start`, and a build without it degrades to
an inert reader with an error in the log.
"""

from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Callable

from ..logger import Logger
from .models import TelemetryFrame


def acc_frame_to_frame(acc_frame) -> TelemetryFrame:
    """Map an ``acc.model.Frame`` dataclass to the app's ``TelemetryFrame``.

    The feed's dataclass deliberately uses the schema's field names — the
    NDJSON proxy serializes it with ``dataclasses.asdict`` and the app model
    validates the result — so the in-process mapping is the same ``asdict``,
    just validated here instead of on the wire. Channels ACC doesn't provide
    (engine_rpm, wheels, rpm_alert, …) take the schema's defaults, and
    ``native_delta_ms`` / ``track_name`` come through set, which switches
    ``DeltaSignal`` / ``TrackSignal`` to their republish paths.
    """
    return TelemetryFrame(**dataclasses.asdict(acc_frame))


class AccDirectReader:
    """TelemetryReaderProtocol over an ACC Broadcasting ``Feed``.

    Like ``Gt7DirectReader``, an instance is not restartable after ``stop()``
    — ``TelemetrySource`` discards it on every mode switch or reconfigure.
    A failed ``start()`` (library missing, no route to the game PC) leaves
    the reader inert: ``latest()`` keeps returning ``None`` and the
    dashboard honestly shows no data.
    """

    def __init__(
        self,
        pc_ip: str,
        feed_factory: Callable[[str], object] | None = None,
    ):
        self.logger = Logger(__class__.__name__).get()
        self._pc_ip = pc_ip
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
                from acc import Feed
            except ImportError as e:
                self.logger.error(
                    f"acc-telemetry is not installed; direct ACC telemetry "
                    f"is unavailable: {e}"
                )
                return
            factory = Feed

        try:
            feed = factory(self._pc_ip)
            feed.start()
        except OSError as e:
            self.logger.error(
                f"Could not open direct ACC telemetry feed for "
                f"{self._pc_ip}: {e}"
            )
            return

        self._feed = feed
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.logger.info(f"Direct ACC telemetry started for {self._pc_ip}")

    def _run(self) -> None:
        feed = self._feed
        while self._running:
            acc_frame = feed.get_latest(timeout=1.0)
            if acc_frame is None:
                continue
            if acc_frame.flags.paused:
                # Same policy as the proxies: hold the last frame while paused.
                continue
            try:
                self._latest = acc_frame_to_frame(acc_frame)
            except Exception as e:
                # One bad frame must not kill the reader, but total loss
                # must not be silent either (see UdpJsonlReader).
                self._dropped += 1
                now = time.monotonic()
                if now - self._last_drop_log >= 5.0:
                    self._last_drop_log = now
                    self.logger.warning(
                        f"Dropped {self._dropped} unmappable ACC "
                        f"frame(s) so far; last error: {e}"
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
