"""Telemetry link supervision.

The cluster's readers hold the last frame they received indefinitely: there
is no TTL on ``UdpJsonlReader._latest``. Without a supervisor, a console
going to sleep, a game exiting, a crashed feed or a dropped Wi-Fi link
leaves the dashboard displaying the last speed, gear and RPM forever —
pixel-identical to live data. A factory dash's first duty is to say when it
no longer knows; this is the signal that lets it.

Freshness is measured off ``TelemetryFrame.received_time``, which the reader
stamps on arrival (see ``UdpJsonlReader._run``). A value that stops changing
means no packet arrived, whatever the reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..telemetry.models import TelemetryFrame
from .signal_keys import SignalKey

# No fresh frame for this long and the link is considered dead. Feeds run at
# 60 Hz, so 1 s is ~60 missed frames — far beyond jitter, short enough that
# the driver learns about it within a corner.
_STALE_AFTER_S = 1.0

# A paused or loading game legitimately stops sending (GT7 emits nothing
# while paused), so the same 1 s would cry wolf on every pause. Allow a much
# longer grace there — but not an unlimited one, because "paused" is also the
# last thing we hear before someone switches the console off entirely.
_STALE_AFTER_PAUSED_S = 10.0


class LinkSignal:
    """Publishes whether the telemetry link is live.

    - ``telemetry_stale`` — True when no frame has arrived recently.
    - ``telemetry_age_s`` — seconds since the last fresh frame.
    """

    def __init__(
        self,
        stale_after_s: float = _STALE_AFTER_S,
        stale_after_paused_s: float = _STALE_AFTER_PAUSED_S,
    ):
        self._stale_after_s = float(stale_after_s)
        self._stale_after_paused_s = float(stale_after_paused_s)
        # None (not 0.0) so the very first frame counts as fresh — 0.0 is a
        # legitimate received_time for a reader that has never been stamped.
        self._last_received_time: float | None = None
        self._age: float = 0.0

    def reset(self) -> None:
        """Forget the link history (new session / telemetry source)."""
        self._last_received_time = None
        self._age = 0.0

    def update(self, frame: TelemetryFrame | None, signals: dict, dt: float) -> dict:
        # No frame at all — a reader that never produced one (an inert direct
        # reader, or a feed that has not connected yet). That is exactly the
        # case the driver most needs told about, so it ages like any other.
        if frame is None:
            self._age += max(0.0, dt)
            return self._publish(self._stale_after_s)

        received_time = frame.received_time
        if received_time != self._last_received_time:
            self._last_received_time = received_time
            self._age = 0.0
        else:
            self._age += max(0.0, dt)

        return self._publish(self._threshold_for(frame))

    def _threshold_for(self, frame: TelemetryFrame) -> float:
        flags = frame.flags
        if flags is not None and (flags.paused or flags.loading_or_processing):
            return self._stale_after_paused_s
        return self._stale_after_s

    def _publish(self, threshold: float) -> dict:
        return {
            SignalKey.TELEMETRY_STALE: self._age >= threshold,
            SignalKey.TELEMETRY_AGE_S: self._age,
        }
