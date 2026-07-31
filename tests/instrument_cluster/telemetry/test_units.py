"""Tests for the session-latched pedal normalizer (telemetry/units.py).

The proxy feeds are released separately from the cluster, so a consumer
cannot assume the schema's 0..1 pedal range actually holds — a feed that
forwards GT7's raw bytes must latch the normalizer into /255 mode.
"""

from instrument_cluster.telemetry.units import ThrottleNormalizer


# --- normalized feeds (schema-conforming) ---


def test_unit_range_passes_through():
    norm = ThrottleNormalizer()
    assert norm(0.0) == 0.0
    assert norm(0.42) == 0.42
    assert norm(1.0) == 1.0


def test_unit_range_is_clamped():
    norm = ThrottleNormalizer()
    assert norm(-0.1) == 0.0
    # 1.0 < v <= 1.5 is jitter on a conforming feed, not proof of raw
    # mode: clamp, don't latch.
    assert norm(1.2) == 1.0
    assert not norm._raw_mode


# --- raw-byte feeds ---


def test_raw_value_latches_divide_mode():
    norm = ThrottleNormalizer()
    assert norm(255) == 1.0
    # once latched, small values are scaled too — raw 51 is 20% pedal,
    # not 100%
    assert norm(51) == 51 / 255
    assert norm(0) == 0.0


def test_pre_latch_raw_idle_is_harmlessly_small():
    """A raw feed idling at 0/1 before the first real pedal input reads as
    at most ~0.4% throttle mis-scaled — indistinguishable from noise."""
    norm = ThrottleNormalizer()
    assert norm(1) == 1.0  # mis-read, but bounded and one-off
    assert norm(200) == 200 / 255  # first real input latches raw mode
    assert norm(1) == 1 / 255


def test_reset_rearms_detection():
    norm = ThrottleNormalizer()
    norm(255)
    assert norm._raw_mode
    norm.reset()
    assert not norm._raw_mode
    assert norm(0.7) == 0.7
