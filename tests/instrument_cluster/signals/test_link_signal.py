"""Tests for LinkSignal — telemetry link supervision.

The readers hold their last frame forever, so without this signal a dead
console, a crashed feed or a dropped Wi-Fi link leaves the dashboard showing
the last speed and gear indefinitely, indistinguishable from live data.
"""
from dataclasses import dataclass, field
from typing import Any

import pytest

from instrument_cluster.signals.link_signal import LinkSignal
from instrument_cluster.signals.signal_keys import SignalKey


@dataclass
class FakeFlags:
    paused: bool = False
    loading_or_processing: bool = False


@dataclass
class FakeFrame:
    received_time: float = 1.0
    flags: Any = field(default_factory=FakeFlags)


DT = 1 / 60


@pytest.fixture
def link():
    return LinkSignal(stale_after_s=1.0, stale_after_paused_s=10.0)


def _pump(link, frame, seconds, dt=DT):
    """Feed the same frame for `seconds` and return the final output."""
    out = {}
    for _ in range(int(seconds / dt)):
        out = link.update(frame, {}, dt)
    return out


def test_fresh_frames_are_never_stale(link):
    out = {}
    for i in range(600):  # 10 s of 60 Hz traffic
        out = link.update(FakeFrame(received_time=float(i)), {}, DT)
    assert out[SignalKey.TELEMETRY_STALE] is False
    assert out[SignalKey.TELEMETRY_AGE_S] == pytest.approx(0.0)


def test_repeated_received_time_goes_stale(link):
    """A reader handing back the same frame is a dead link, not live data."""
    frame = FakeFrame(received_time=42.0)
    link.update(frame, {}, DT)

    out = _pump(link, frame, seconds=0.5)
    assert out[SignalKey.TELEMETRY_STALE] is False, "0.5 s is within tolerance"

    out = _pump(link, frame, seconds=1.0)
    assert out[SignalKey.TELEMETRY_STALE] is True
    assert out[SignalKey.TELEMETRY_AGE_S] >= 1.0


def test_link_recovers_when_frames_resume(link):
    frame = FakeFrame(received_time=42.0)
    assert _pump(link, frame, seconds=2.0)[SignalKey.TELEMETRY_STALE] is True

    out = link.update(FakeFrame(received_time=43.0), {}, DT)
    assert out[SignalKey.TELEMETRY_STALE] is False
    assert out[SignalKey.TELEMETRY_AGE_S] == pytest.approx(0.0)


def test_paused_game_gets_a_longer_grace_period(link):
    """GT7 stops sending while paused — that must not read as a dead link."""
    frame = FakeFrame(received_time=7.0, flags=FakeFlags(paused=True))
    link.update(frame, {}, DT)

    out = _pump(link, frame, seconds=5.0)
    assert out[SignalKey.TELEMETRY_STALE] is False, "still just paused"

    out = _pump(link, frame, seconds=6.0)
    assert out[SignalKey.TELEMETRY_STALE] is True, (
        "a pause that never ends is indistinguishable from a console "
        "switched off — it must not suppress the warning forever"
    )


def test_loading_screen_gets_the_same_grace_as_a_pause(link):
    frame = FakeFrame(
        received_time=7.0, flags=FakeFlags(loading_or_processing=True)
    )
    link.update(frame, {}, DT)
    assert _pump(link, frame, seconds=5.0)[SignalKey.TELEMETRY_STALE] is False


def test_no_frame_at_all_is_stale(link):
    """An inert reader (failed direct reader, feed never connected) produces
    no frame — the case the driver most needs told about."""
    out = {}
    for _ in range(120):  # 2 s
        out = link.update(None, {}, DT)
    assert out[SignalKey.TELEMETRY_STALE] is True


def test_first_frame_with_zero_received_time_counts_as_fresh(link):
    """0.0 is a legitimate stamp; only a *repeat* means no new packet."""
    out = link.update(FakeFrame(received_time=0.0), {}, DT)
    assert out[SignalKey.TELEMETRY_STALE] is False


def test_reset_forgets_history(link):
    frame = FakeFrame(received_time=42.0)
    assert _pump(link, frame, seconds=2.0)[SignalKey.TELEMETRY_STALE] is True

    link.reset()
    out = link.update(frame, {}, DT)
    assert out[SignalKey.TELEMETRY_STALE] is False
