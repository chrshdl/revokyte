from dataclasses import dataclass, field

import pytest

from instrument_cluster.signals.signal_keys import SignalKey
from instrument_cluster.ui.colors import Color
from instrument_cluster.ui.widgets.fuel_laps_widget import FuelLapsWidget
from instrument_cluster.ui.widgets.fuel_per_lap_widget import FuelPerLapWidget


@dataclass
class MockTelemetryFrame:
    lap_count: int = 0


@dataclass
class MockVehicleBus:
    frame: MockTelemetryFrame = field(default_factory=MockTelemetryFrame)
    signals: dict = field(default_factory=dict)


# --- Fixtures ---


@pytest.fixture
def bus():
    return MockVehicleBus()


@pytest.fixture
def per_lap():
    return FuelPerLapWidget(rect=(0, 0, 172, 94))


@pytest.fixture
def laps():
    return FuelLapsWidget(rect=(0, 0, 172, 94))


# --- Formatting Tests ---


def test_placeholder_when_value_is_none(per_lap, laps):
    assert per_lap._last_value_str == "--.-"
    assert laps._last_value_str == "--.-"


def test_per_lap_formats_two_decimals(per_lap):
    per_lap.set_value(2.64)
    assert per_lap._last_value_str == "2.64"


def test_laps_formats_one_decimal(laps):
    laps.set_value(12.37)
    assert laps._last_value_str == "12.4"


def test_laps_caps_at_display_maximum(laps):
    laps.set_value(123.4)
    assert laps._last_value_str == "99.9"


# --- Low-fuel warning color ---


def test_laps_color_white_when_plenty(laps):
    laps.set_value(5.0)
    assert laps._last_color == laps.text_color


def test_laps_color_yellow_below_warn_threshold(laps):
    laps.set_value(2.9)
    assert laps._last_color == Color.YELLOW.rgb()


def test_laps_color_red_below_critical_threshold(laps):
    laps.set_value(0.8)
    assert laps._last_color == Color.LIGHT_RED.rgb()


def test_laps_color_neutral_for_placeholder(laps):
    laps.set_value(0.5)
    laps.set_value(None)
    assert laps._last_color == laps.text_color


def test_threshold_crossing_marks_dirty_even_if_string_same(laps):
    laps.set_value(3.0)  # white
    laps.dirty = 0
    # 2.99 still renders "3.0" but must repaint yellow.
    laps.set_value(2.99)
    assert laps.dirty == 1
    assert laps._last_color == Color.YELLOW.rgb()


# --- State & UI Logic Tests ---


def test_set_value_marks_dirty_on_change(per_lap):
    per_lap.dirty = 0
    per_lap.set_value(2.6)
    assert per_lap.dirty == 1

    per_lap.dirty = 0
    per_lap.set_value(2.6)
    assert per_lap.dirty == 0  # same string — no redraw

    per_lap.set_value(None)
    assert per_lap.dirty == 1  # back to placeholder


# --- Update & Bus Integration Tests ---


def test_update_reads_signals_from_bus(per_lap, laps, bus):
    bus.signals[SignalKey.FUEL_USED_CURRENT_LAP] = 2.6
    bus.signals[SignalKey.FUEL_LAPS_REMAINING] = 12.4

    per_lap.update(bus, dt=0.01)
    laps.update(bus, dt=0.01)

    assert per_lap._last_value_str == "2.60"
    assert laps._last_value_str == "12.4"


def test_update_missing_signal_shows_placeholder(per_lap, bus):
    per_lap.set_value(2.6)
    per_lap.update(bus, dt=0.01)  # key absent from bus.signals
    assert per_lap._last_value_str == "--.-"


def test_update_ignores_missing_frame(per_lap, bus):
    per_lap.set_value(2.6)
    bus.frame = None
    bus.signals[SignalKey.FUEL_USED_CURRENT_LAP] = 9.9

    per_lap.update(bus, dt=0.01)

    assert per_lap._last_value_str == "2.60"  # unchanged, no crash
