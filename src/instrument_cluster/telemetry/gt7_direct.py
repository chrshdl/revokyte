"""In-process GT7 telemetry for the desktop build.

Drives a :class:`granturismo.Feed` (the same library the appliance's proxy
program wraps) on a background thread and republishes each decoded packet as
a :class:`TelemetryFrame` — the proxy's data path minus the separate process
and the NDJSON round-trip. Referenced only by the granturismo entry in
``addons/feeds.py``; nothing else in the app knows this module exists.

``granturismo`` is an optional dependency (the ``pc`` extra): the import is
deferred to :meth:`Gt7DirectReader.start`, and a build without it degrades to
an inert reader with an error in the log.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from ..logger import Logger
from .models import Bounds, Flags, TelemetryFrame, Vector, Wheel, Wheels


def _wheel(w) -> Wheel:
    return Wheel(
        # The schema constrains suspension to [0, 1]; clamp instead of letting
        # a marginally out-of-range float drop the whole frame.
        suspension_height=min(1.0, max(0.0, w.suspension_height)),
        radius=w.radius,
        rps=w.rps,
        ground_speed=w.ground_speed,
        temperature=w.temperature,
    )


def packet_to_frame(packet) -> TelemetryFrame:
    """Map a granturismo ``Packet`` (or anything shaped like one) to the
    app's ``TelemetryFrame`` schema.

    Field names match what the NDJSON proxy emits; the one deliberate
    difference is ``current_gear``: the packet reports neutral as ``None``,
    which the schema encodes as ``-1``.
    """
    pf = packet.flags
    pw = packet.wheels
    return TelemetryFrame(
        received_time=packet.received_time,
        car_id=packet.car_id,
        car_speed=packet.car_speed,
        engine_rpm=packet.engine_rpm,
        current_gear=-1 if packet.current_gear is None else packet.current_gear,
        # granturismo exposes the packet's raw pedal bytes (0-255); the
        # schema wants 0..1.
        throttle=min(1.0, packet.throttle / 255.0),
        brake=min(1.0, packet.brake / 255.0),
        gas_level=packet.gas_level,
        gas_capacity=packet.gas_capacity,
        lap_count=packet.lap_count,
        laps_in_race=packet.laps_in_race,
        best_lap_time=packet.best_lap_time,
        last_lap_time=packet.last_lap_time,
        current_lap_time=packet.current_lap_time,
        flags=Flags(
            car_on_track=pf.car_on_track,
            paused=pf.paused,
            loading_or_processing=pf.loading_or_processing,
            in_gear=pf.in_gear,
            has_turbo=pf.has_turbo,
            rev_limiter_alert_active=pf.rev_limiter_alert_active,
            hand_brake_active=pf.hand_brake_active,
            lights_active=pf.lights_active,
            lights_high_beams_active=pf.lights_high_beams_active,
            lights_low_beams_active=pf.lights_low_beams_active,
            asm_active=pf.asm_active,
            tcs_active=pf.tcs_active,
        ),
        rpm_alert=Bounds(min=packet.rpm_alert.min, max=packet.rpm_alert.max),
        wheels=Wheels(
            front_left=_wheel(pw.front_left),
            front_right=_wheel(pw.front_right),
            rear_left=_wheel(pw.rear_left),
            rear_right=_wheel(pw.rear_right),
        ),
        position=Vector(
            x=packet.position.x, y=packet.position.y, z=packet.position.z
        ),
        gear_ratios=list(packet.gear_ratios),
    )


class Gt7DirectReader:
    """TelemetryReaderProtocol over a granturismo ``Feed``.

    Like ``UdpJsonlReader``, an instance is not restartable after ``stop()``
    — ``TelemetrySource`` discards it on every mode switch or reconfigure.
    A failed ``start()`` (library missing, telemetry port already bound)
    leaves the reader inert: ``latest()`` keeps returning ``None`` and the
    dashboard honestly shows no data.
    """

    def __init__(
        self,
        ps_ip: str,
        feed_factory: Callable[[str], object] | None = None,
    ):
        self.logger = Logger(__class__.__name__).get()
        self._ps_ip = ps_ip
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
                from granturismo import Feed
            except ImportError as e:
                self.logger.error(
                    f"granturismo is not installed; direct GT7 telemetry "
                    f"is unavailable: {e}"
                )
                return
            factory = Feed

        try:
            feed = factory(self._ps_ip)
            feed.start()
        except OSError as e:
            # Most likely the GT7 telemetry port (33740) is already bound —
            # e.g. a proxy or second dashboard instance is running.
            self.logger.error(
                f"Could not open direct GT7 telemetry feed for "
                f"{self._ps_ip}: {e}"
            )
            return

        self._feed = feed
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.logger.info(f"Direct GT7 telemetry started for {self._ps_ip}")

    def _run(self) -> None:
        feed = self._feed
        while self._running:
            packet = feed.get_latest(timeout=1.0)
            if packet is None:
                continue
            if packet.flags.paused:
                # Same policy as the proxy: hold the last frame while paused.
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
                        f"Dropped {self._dropped} unmappable GT7 "
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
