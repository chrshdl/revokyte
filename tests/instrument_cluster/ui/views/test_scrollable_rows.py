"""The scrollable settings list must only pay for itself while it moves.

`is_scrollable` means the content overflows; `in_motion` means the offset is
actually changing. Conflating them made every stationary Setup frame a
full-screen flush — 6.42 ms against 0.29 ms for a dirty-rect frame on a Pi 4,
which is the 7% -> 20% CPU jump on entering Setup.
"""

import pygame
import pytest

from instrument_cluster.config import ConfigManager
from instrument_cluster.ui.views.setup_view import SetupView
from instrument_cluster.ui.widgets.base.list_item import ListItem, ListItemGroup


@pytest.fixture(autouse=True)
def config_path(tmp_path):
    ConfigManager.set_path(tmp_path / "config.json")
    ConfigManager.reset()
    yield


@pytest.fixture
def scrolling_view(monkeypatch):
    """A SetupView whose list overflows, as it does on the 7-inch panel."""
    import instrument_cluster.ui.views.setup_view as module

    monkeypatch.setattr(module, "is_raspberry_pi", lambda: True)
    view = SetupView()
    # Force overflow regardless of how many rows this build contributes.
    view.scrollbar.content_height = view.scrollbar.viewport_height + 200
    assert view.scrollbar.is_scrollable
    return view


def _surfaces():
    return pygame.Surface((1024, 600)), pygame.Surface((1024, 600))


# --------------------------------------------------------------------------
# in_motion
# --------------------------------------------------------------------------
def test_overflow_alone_is_not_motion(scrolling_view):
    assert scrolling_view.scrollbar.is_scrollable
    assert not scrolling_view.scrollbar.in_motion


def test_dragging_and_gliding_both_count_as_motion(scrolling_view):
    sb = scrolling_view.scrollbar

    sb._gesture_dragging = True
    assert sb.in_motion
    sb._gesture_dragging = False

    sb._thumb_dragging = True
    assert sb.in_motion
    sb._thumb_dragging = False

    sb._velocity = -120.0
    assert sb.in_motion, "momentum after a flick is still motion"
    sb._velocity = 0.0
    assert not sb.in_motion


# --------------------------------------------------------------------------
# the draw path
# --------------------------------------------------------------------------
def test_a_stationary_list_does_not_flush_the_whole_screen(scrolling_view):
    surface, background = _surfaces()
    scrolling_view.full_paint(surface, background)
    scrolling_view.draw(surface, background)          # settle into a mode

    rects = scrolling_view.draw(surface, background)

    full = surface.get_rect()
    assert not any(r == full for r in rects), (
        "a stationary list took the immediate-mode path and flushed the "
        "entire panel"
    )


def test_a_moving_list_does_take_the_immediate_path(scrolling_view):
    surface, background = _surfaces()
    scrolling_view.full_paint(surface, background)
    scrolling_view.draw(surface, background)

    scrolling_view.scrollbar._gesture_dragging = True
    scrolling_view.draw(surface, background)          # mode switch frame
    rects = scrolling_view.draw(surface, background)

    assert rects == [surface.get_rect()], (
        "while dragging, rows move every frame and the viewport must be "
        "redrawn wholesale"
    )


def test_settling_rebakes_the_separators_into_the_background(scrolling_view):
    surface, background = _surfaces()
    sb = scrolling_view.scrollbar
    scrolling_view.full_paint(surface, background)
    scrolling_view.draw(surface, background)

    sb._gesture_dragging = True
    scrolling_view.draw(surface, background)
    assert scrolling_view._live_scroll
    assert scrolling_view._baked_offset is None, "live path owns the separators"

    sb._gesture_dragging = False
    sb.offset = 40.0
    scrolling_view.draw(surface, background)

    assert not scrolling_view._live_scroll
    assert scrolling_view._baked_offset == 40.0, (
        "at rest the separators belong in the background, at the offset the "
        "rows actually sit at"
    )


def test_an_offset_moved_without_a_gesture_is_still_rebaked(scrolling_view):
    """reset(), or a view rebuilding its rows, moves the offset with no
    motion either side of it — the background must not keep the old
    separators."""
    surface, background = _surfaces()
    scrolling_view.full_paint(surface, background)
    scrolling_view.draw(surface, background)
    assert scrolling_view._baked_offset == 0.0

    scrolling_view.scrollbar.offset = 77.0
    scrolling_view.draw(surface, background)

    assert scrolling_view._baked_offset == 77.0


# --------------------------------------------------------------------------
# the other half: scroll_to dirtying every row, every frame
# --------------------------------------------------------------------------
def test_repeating_an_offset_does_not_dirty_every_row():
    rows = ListItemGroup(ListItem(y=i * 60, widgets=[]) for i in range(4))
    rows.scroll_to(30.0)
    for row in rows:
        for sprite in row.sprites():
            sprite.dirty = 0

    rows.scroll_to(30.0)

    dirty = [s.dirty for row in rows for s in row.sprites()]
    assert not any(dirty), (
        "the owning view calls scroll_to() every frame; repeating the same "
        "offset must not mark the whole list for repaint"
    )


def test_a_new_offset_still_dirties_the_rows():
    rows = ListItemGroup(ListItem(y=i * 60, widgets=[]) for i in range(4))
    rows.scroll_to(30.0)
    for row in rows:
        for sprite in row.sprites():
            sprite.dirty = 0

    rows.scroll_to(31.0)

    assert all(s.dirty for row in rows for s in row.sprites())


def test_force_reapplies_the_same_offset():
    rows = ListItemGroup(ListItem(y=i * 60, widgets=[]) for i in range(4))
    rows.scroll_to(0.0)
    for row in rows:
        for sprite in row.sprites():
            sprite.dirty = 0

    rows.scroll_to(0.0, force=True)

    assert all(s.dirty for row in rows for s in row.sprites())
