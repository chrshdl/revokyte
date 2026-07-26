"""Display-refresh throttling of the lap clock widgets.

CurrentLapTimeWidget's raw value changes every frame (a millisecond clock),
so its *rendered* text refreshes at 10 Hz. PredictedLapTimeWidget's input is
already rate-limited by delta_diff_stable, so it only re-formats when the
raw value actually changed.
"""

from dataclasses import dataclass, field

import pytest

from instrument_cluster.signals.signal_keys import SignalKey
from instrument_cluster.ui.widgets.current_lap_time_widget import CurrentLapTimeWidget
from instrument_cluster.ui.widgets.predicted_lap_time_widget import (
    PredictedLapTimeWidget,
)

_DT_60HZ = 1.0 / 60.0


@dataclass
class MockTelemetryFrame:
    lap_count: int = 1
    current_lap_time: int | None = 0  # ms


@dataclass
class MockVehicleBus:
    frame: MockTelemetryFrame = field(default_factory=MockTelemetryFrame)
    signals: dict = field(default_factory=dict)


@pytest.fixture
def bus():
    return MockVehicleBus()


@pytest.fixture
def clock():
    return CurrentLapTimeWidget(rect=(0, 0, 258, 94))


@pytest.fixture
def predicted():
    return PredictedLapTimeWidget(rect=(0, 0, 258, 94))


# --- CurrentLapTimeWidget ---


def test_first_live_value_paints_immediately(clock, bus):
    bus.frame.current_lap_time = 12340
    clock.update(bus, _DT_60HZ)
    assert clock._last_value_str == "00:12.34"


def test_display_refreshes_at_10hz_not_60hz(clock, bus):
    bus.frame.current_lap_time = 12340
    clock.update(bus, _DT_60HZ)

    # Six more 60 Hz frames (~100 ms minus float dust): the clock advances,
    # the text must not.
    for i in range(6):
        bus.frame.current_lap_time = 12340 + (i + 1) * 17
        clock.update(bus, _DT_60HZ)
    assert clock._last_value_str == "00:12.34"

    # The seventh frame crosses the 100 ms refresh interval.
    bus.frame.current_lap_time = 12467
    clock.update(bus, _DT_60HZ)
    assert clock._last_value_str == "00:12.46"


def test_reset_paints_immediately_and_rearms(clock, bus):
    bus.frame.current_lap_time = 12340
    clock.update(bus, _DT_60HZ)

    # Out of the lap (menu / pre-race): placeholder must not wait 100 ms.
    bus.frame.lap_count = 0
    clock.update(bus, _DT_60HZ)
    assert clock._last_value_str == "00:00.00"

    # Back on track: the first live value must not wait either.
    bus.frame.lap_count = 1
    bus.frame.current_lap_time = 500
    clock.update(bus, _DT_60HZ)
    assert clock._last_value_str == "00:00.50"


# --- PredictedLapTimeWidget ---


def test_unchanged_stable_delta_skips_formatting(predicted, bus):
    bus.signals = {
        SignalKey.DELTA_DIFF_STABLE: 0.25,
        SignalKey.DELTA_REF_LAP_TIME: 92.0,
    }
    calls = 0
    original = predicted.format_mm_ss_hh

    def counting(seconds):
        nonlocal calls
        calls += 1
        return original(seconds)

    predicted.format_mm_ss_hh = counting

    for _ in range(60):
        predicted.update(bus, _DT_60HZ)

    assert predicted._last_value_str == "01:32.25"
    assert calls == 1


def test_changed_stable_delta_repaints(predicted, bus):
    bus.signals = {
        SignalKey.DELTA_DIFF_STABLE: 0.25,
        SignalKey.DELTA_REF_LAP_TIME: 92.0,
    }
    predicted.update(bus, _DT_60HZ)
    assert predicted._last_value_str == "01:32.25"

    bus.signals[SignalKey.DELTA_DIFF_STABLE] = -0.75
    predicted.update(bus, _DT_60HZ)
    assert predicted._last_value_str == "01:31.25"
