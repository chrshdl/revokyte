"""Unit guards for telemetry values whose scale depends on the feed.

The ``TelemetryFrame`` schema defines pedal positions as 0..1, and the
in-process readers normalize (``gt7_direct``), but the NDJSON proxy feeds
are released separately — an installed feed may still emit GT7's raw
0-255 pedal bytes. Consumers that act on throttle route it through a
``ThrottleNormalizer`` so a raw-byte feed degrades to correct values
instead of a pinned-at-1.0 pedal.
"""


class ThrottleNormalizer:
    """Session-latched 0..1 normalizer for pedal values.

    A single value cannot be classified (raw ``1`` is 0.4% pedal, normalized
    ``1.0`` is full throttle), so the scale is latched for the whole session:
    the first value above ``_RAW_THRESHOLD`` proves the feed emits raw bytes,
    and every subsequent value is divided by 255. Until then values are
    clamped to [0, 1] — mis-scaling a raw feed's pre-latch idle creep is
    bounded by 1.5/255 of pedal, which no consumer can distinguish from
    noise. ``reset()`` on car change / feed switch re-arms detection.
    """

    _RAW_THRESHOLD = 1.5

    def __init__(self) -> None:
        self._raw_mode = False

    def reset(self) -> None:
        self._raw_mode = False

    def __call__(self, value: float) -> float:
        if value > self._RAW_THRESHOLD:
            self._raw_mode = True
        if self._raw_mode:
            return min(1.0, max(0.0, value / 255.0))
        return min(1.0, max(0.0, value))
