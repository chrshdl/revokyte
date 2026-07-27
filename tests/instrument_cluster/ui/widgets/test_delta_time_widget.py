from dataclasses import dataclass, field

import pygame
import pytest

from instrument_cluster.signals.signal_keys import DeltaState
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

    # None signal: the number must NOT be held. A delta left over from an
    # earlier lap, reference or track is indistinguishable from a live one.
    bus.signals["delta_diff_stable"] = None
    widget.update(bus, dt=0.1)
    assert widget._last_rendered_value is None
    assert widget._last_value_str == ""


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
    assert widget.header_text == "Time  Diff  [Fastest]"

    bus.signals["delta_reference_mode"] = "previous"
    widget.update(bus, dt=0.01)
    assert widget.header_text == "Time  Diff  [Previous]"

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
    assert widget.header_text == "Time  Diff  [Previous]"
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


# --- Empty-state Tests ---
#
# A blank delta gauge is ambiguous — it reads the same as a broken one — and
# a held-over number is worse still: a delta from an earlier lap, reference
# or track is indistinguishable from a live one.


def test_no_delta_shows_the_reason_not_the_last_number(widget, bus):
    """Regression: the widget used to skip set_value() on a None signal and
    keep displaying the previous delta indefinitely."""
    bus.frame.lap_count = 3
    bus.signals["delta_diff_stable"] = -0.42
    widget.update(bus, dt=0.1)
    assert widget._last_value_str == "00.42"

    # Track change discards the reference: the old number must go.
    bus.signals["delta_diff_stable"] = None
    bus.signals["delta_state"] = DeltaState.NO_REF
    widget.update(bus, dt=0.1)

    assert widget._last_value_str == "NO REF"
    assert widget._last_rendered_value is None


@pytest.mark.parametrize(
    "state, expected",
    [
        (DeltaState.BEACON, "BEACON"),
        (DeltaState.REF_LAP, "REF LAP"),
        (DeltaState.NO_REF, "NO REF"),
        (None, ""),
        ("something-unknown", ""),
    ],
)
def test_state_words(widget, bus, state, expected):
    bus.frame.lap_count = 2
    bus.signals["delta_diff_stable"] = None
    bus.signals["delta_state"] = state
    widget.update(bus, dt=0.1)
    assert widget._last_value_str == expected


def test_state_word_shown_before_the_first_timed_lap(widget, bus):
    """lap_count 0 — waiting for the start/finish beacon."""
    bus.frame.lap_count = 0
    bus.signals["delta_state"] = DeltaState.BEACON
    widget.update(bus, dt=0.1)
    assert widget._last_value_str == "BEACON"


def test_number_replaces_the_state_word_once_armed(widget, bus):
    bus.frame.lap_count = 2
    bus.signals["delta_diff_stable"] = None
    bus.signals["delta_state"] = DeltaState.REF_LAP
    widget.update(bus, dt=0.1)
    assert widget._last_value_str == "REF LAP"

    bus.signals["delta_diff_stable"] = 1.5
    bus.signals["delta_state"] = None
    widget.update(bus, dt=0.1)

    assert widget._last_value_str == "01.50"
    assert widget._last_rendered_value == 1.5


def test_state_render_is_idempotent(widget, bus):
    """Repainting the same state must not mark the sprite dirty every frame
    (dirty-rect rendering would flush the panel at 60 fps for nothing)."""
    bus.frame.lap_count = 2
    bus.signals["delta_diff_stable"] = None
    bus.signals["delta_state"] = DeltaState.REF_LAP
    widget.update(bus, dt=0.1)

    widget.dirty = 0
    for _ in range(10):
        widget.update(bus, dt=0.1)
    assert widget.dirty == 0


def test_nan_delta_falls_back_to_the_state_word(widget, bus):
    bus.frame.lap_count = 2
    bus.signals["delta_diff_stable"] = float("nan")
    bus.signals["delta_state"] = DeltaState.REF_LAP
    widget.update(bus, dt=0.1)
    assert widget._last_value_str == "REF LAP"


@pytest.fixture
def panel():
    """The gauge at its production rect (see plugins/delta.py).

    The shared `widget` fixture is 200x100; the state font is a fixed design
    size, so geometry only means anything against the real panel.
    """
    from instrument_cluster.ui.utils import srect

    return DeltaTimeWidget(rect=srect(1094, 308, 336, 150))


def test_state_word_sits_above_the_value_area_centre(panel, bus):
    """The state word is lifted off the value area's centre.

    The value area begins below the header, so its centre sits low in the
    panel — geometrically right, optically wrong: the eye centres the word
    against the box. It must not inherit value_offset_y either, which is
    sized for the number (that has the segment tracker beneath it too).
    """
    bus.frame.lap_count = 2
    bus.signals["delta_diff_stable"] = None
    bus.signals["delta_state"] = DeltaState.REF_LAP
    panel.update(bus, dt=0.1)

    area = panel._value_area()
    top, bottom = _ink_rows(panel, area)
    text_centre_y = (top + bottom) / 2 + area.top
    lift = area.centery - text_centre_y

    assert lift == pytest.approx(panel.state_offset_y, abs=3)
    assert 0 < panel.state_offset_y < panel.value_offset_y


def _ink_rows(widget, area):
    """First and last row inside `area` holding glyph pixels.

    Not get_bounding_rect(): the panel background is opaque, so that returns
    the whole area and makes any offset assertion pass trivially. The scan is
    also inset horizontally — the rounded border bleeds into the area's edge
    columns, and those pixels would otherwise read as text near the bottom.
    """
    import numpy as np
    import pygame

    scan = area.inflate(-12, 0)
    pixels = pygame.surfarray.array3d(widget.image.subsurface(scan))
    # array3d is [x][y][rgb]; glyphs are the only thing lighter than the fill.
    lit = (pixels.max(axis=2) > max(widget.bg_color) + 12).any(axis=0)
    rows = np.flatnonzero(lit)
    assert rows.size, "no glyph pixels found in the value area"
    return int(rows[0]), int(rows[-1])


@pytest.mark.parametrize("word", ["BEACON", "REF LAP", "NO REF"])
def test_state_words_fit_the_panel(panel, word):
    """No token may overrun the panel — BEACON is the widest in D-DIN."""
    area = panel._value_area()
    surf = panel._state_font.render(word, True, (255, 255, 255))

    assert surf.get_width() < area.width
    assert surf.get_height() < area.height


def test_header_uses_the_same_words_as_the_setup_dropdown():
    """One setting must not have two vocabularies.

    Setup's Reference Lap dropdown renders the raw DiffReferenceMode values,
    so the dash header has to name the mode the same way — otherwise the
    driver picks "fastest" and the gauge reports "[Best]".
    """
    from instrument_cluster.ui.widgets.delta_time_widget import _MODE_HEADERS
    from instrument_cluster.telemetry.mode import DiffReferenceMode

    for mode in DiffReferenceMode:
        header = _MODE_HEADERS[mode.value]
        assert mode.value in header.lower(), (
            f"{mode.value!r} is what Setup shows, but the header reads "
            f"{header!r}"
        )
