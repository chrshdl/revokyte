from dataclasses import dataclass, field

import pygame
import pytest

from instrument_cluster.ui.colors import Color
from instrument_cluster.ui.widgets.delta_time_widget import DeltaTimeWidget


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
def widget():
    # Initialize without feed, as it's no longer used
    return DeltaTimeWidget(rect=(0, 0, 200, 100))


# --- Formatting Tests ---


def test_format_delta_none(widget):
    text, color = widget._format_delta(None)
    assert text == ""
    assert isinstance(color, tuple)


def test_format_delta_negative_is_green(widget):
    """Negative delta means we are faster (ahead of reference)."""
    text, color = widget._format_delta(-1.234)
    assert text == "01.23"
    assert color == Color.GREEN.rgb()


def test_format_delta_positive_is_light_red(widget):
    """Positive delta means we are slower (behind reference)."""
    text, color = widget._format_delta(2.0)
    assert text == "02.00"
    assert color == Color.LIGHT_RED.rgb()


# --- State & UI Logic Tests ---


def test_set_value_marks_dirty_on_change(widget):
    widget.dirty = 0
    widget._last_value_str = ""

    # Change value
    widget.set_value(1.23)
    assert widget.dirty == 1

    # Reset dirty flag
    widget.dirty = 0

    # Set same value (string representation matches)
    widget.set_value(1.23)
    assert widget.dirty == 0  # Should not be dirty

    # Set None
    widget.set_value(None)
    assert widget.dirty == 1  # Changed from "01.23" to ""


def test_reset_clears_state(widget):
    # Simulate active state
    widget._lap_index = 3
    widget._last_rendered_value = 1.5
    widget._last_value_str = "01.50"

    widget.reset()

    assert widget._lap_index == -1
    assert widget._last_rendered_value is None
    assert widget._last_value_str == ""


# --- Update & Bus Integration Tests ---


def test_update_reads_delta_from_bus(widget, bus):
    """Ensure widget reads 'delta_diff_stable' from bus.signals."""
    bus.signals["delta_diff_stable"] = -0.55
    bus.frame.lap_count = 1

    widget.update(bus, dt=0.01)

    assert widget._last_rendered_value == -0.55
    assert widget._last_value_str == "00.55"


def test_update_ignores_none_delta(widget, bus):
    """If the stable signal is absent, the displayed value stays empty."""
    bus.signals["delta_diff_stable"] = None
    bus.frame.lap_count = 1

    widget.update(bus, dt=0.01)

    assert widget._last_rendered_value is None


def test_update_resets_on_zero_lap_count(widget, bus):
    """Entering the pits or restarting (lap 0) should reset the widget."""
    widget._lap_index = 5
    widget.set_value(1.0)  # go through the API so _last_value_str is also set

    bus.frame.lap_count = 0
    widget.update(bus, dt=0.1)

    assert widget._lap_index == -1
    assert widget._last_rendered_value is None


def test_lap_change_updates_index_and_value(widget, bus):
    """Crossing start/finish updates the lap index and applies the new delta."""
    widget._lap_index = 1

    bus.frame.lap_count = 2
    bus.signals["delta_diff_stable"] = 0.05

    widget.update(bus, dt=0.1)

    assert widget._lap_index == 2
    assert widget._last_rendered_value == 0.05


# --- Sample-and-Hold Logic Tests ---


def test_widget_passes_through_stable_signal(widget, bus):
    """
    Sample-and-hold is handled by DeltaSignal; the widget reads delta_diff_stable
    directly and updates the displayed value on each frame.
    """
    bus.frame.lap_count = 1

    bus.signals["delta_diff_stable"] = 1.0
    widget.update(bus, dt=0.1)
    assert widget._last_rendered_value == 1.0

    bus.signals["delta_diff_stable"] = 2.0
    widget.update(bus, dt=0.1)
    assert widget._last_rendered_value == 2.0

    # None signal: update() skips set_value(); displayed value unchanged
    bus.signals["delta_diff_stable"] = None
    widget.update(bus, dt=0.1)
    assert widget._last_rendered_value == 2.0


# --- Rendering Tests ---


def test_render_segmented_tracker_draws_correct_count(widget, monkeypatch):
    """_render_segmented_tracker draws one polygon per active segment."""
    calls = []
    monkeypatch.setattr(pygame.draw, "polygon", lambda s, c, pts: calls.append((c, pts)))

    area = pygame.Rect(0, 0, 200, 100)
    # round(0.60 * 100) // (100 // 10) = 60 // 10 = 6 segments, green
    widget._render_segmented_tracker(area, -0.60)

    assert len(calls) == 6
    # Negative value -> greenish color (G channel dominates)
    for color, _ in calls:
        assert color[1] > color[0]  # G > R


def test_render_segmented_tracker_caps_at_max_segments(widget, monkeypatch):
    """Large delta must be capped at _max_segments polygons."""
    calls = []
    monkeypatch.setattr(pygame.draw, "polygon", lambda s, c, pts: calls.append(pts))

    area = pygame.Rect(0, 0, 200, 100)
    # 10.0 / 0.05 = 200 segments, capped at _max_segments (10)
    widget._render_segmented_tracker(area, 10.0)

    assert len(calls) == widget._max_segments


# --- Reference-mode header tests ---


def test_header_follows_reference_mode(widget, bus):
    """The header names the active reference so a mode switch is visible even
    when both references read the same delta at the current track position."""
    bus.frame.lap_count = 1
    bus.signals["delta_diff_stable"] = 0.5

    bus.signals["delta_reference_mode"] = "fastest"
    widget.update(bus, dt=0.01)
    assert widget.header_text == "Time  Diff  [Best]"

    bus.signals["delta_reference_mode"] = "previous"
    widget.update(bus, dt=0.01)
    assert widget.header_text == "Time  Diff  [Prev]"

    # No mode published (demo mode / no producer) -> neutral header.
    bus.signals["delta_reference_mode"] = None
    widget.update(bus, dt=0.01)
    assert widget.header_text == "Time  Diff"


def test_header_change_repaints_current_value(widget, bus):
    """Rebuilding the base image for a new header must not lose the value —
    the same delta is repainted onto the fresh base in the same update."""
    bus.frame.lap_count = 1
    bus.signals["delta_diff_stable"] = 0.5
    bus.signals["delta_reference_mode"] = "fastest"
    widget.update(bus, dt=0.01)
    assert widget._last_value_str == "00.50"

    widget.dirty = 0
    bus.signals["delta_reference_mode"] = "previous"
    widget.update(bus, dt=0.01)

    assert widget.dirty == 1
    assert widget.header_text == "Time  Diff  [Prev]"
    assert widget._last_value_str == "00.50"
    assert widget._last_rendered_value == 0.5


def test_header_unchanged_when_mode_stable(widget, bus):
    """A steady mode must not rebuild the base image every frame."""
    bus.frame.lap_count = 1
    bus.signals["delta_reference_mode"] = "fastest"
    bus.signals["delta_diff_stable"] = 0.5
    widget.update(bus, dt=0.01)

    widget.dirty = 0
    widget.update(bus, dt=0.01)
    assert widget.dirty == 0
