"""Screen transitions must allocate nothing.

This is the property the whole ViewRegistry refactor exists to establish. It
is asserted here rather than only measured on device because the failure mode
is invisible in normal use: view surfaces are allocated in C by SDL, so a
regression shows up not as a test failure or a leak but as one abrupt garbage
collection at 3 fps, minutes later, at an arbitrary moment.
"""

from unittest.mock import MagicMock

import pygame
import pytest

from instrument_cluster.states.setup_state import SetupState
from instrument_cluster.states.software_state import SoftwareState
from instrument_cluster.states.state_manager import StateManager
from instrument_cluster.ui.views.registry import core_views, views
from instrument_cluster.ui.views.setup_view import SetupView
from instrument_cluster.ui.views.software_view import SoftwareView


@pytest.fixture
def manager(tmp_path):
    from instrument_cluster.config import ConfigManager

    ConfigManager.set_path(tmp_path / "config.json")
    ConfigManager.reset()
    screen = pygame.Surface((1280, 720))
    return StateManager(screen, MagicMock())


def _count_constructions(monkeypatch, *classes):
    """Wrap each class's __init__ with a counter."""
    counts = {cls: 0 for cls in classes}

    for cls in classes:
        original = cls.__init__

        def counting(self, *a, _cls=cls, _orig=original, **kw):
            counts[_cls] += 1
            return _orig(self, *a, **kw)

        monkeypatch.setattr(cls, "__init__", counting)
    return counts


def test_twenty_setup_visits_construct_exactly_one_view(manager, monkeypatch):
    views.preload(core_views())
    counts = _count_constructions(monkeypatch, SetupView)

    for _ in range(20):
        manager.push_state(SetupState(manager))
        manager.pop_state()

    assert counts[SetupView] == 0, (
        "a preloaded view must never be constructed again; "
        "acquire() is supposed to be a dict lookup"
    )


def test_a_lazy_first_visit_builds_once_and_never_again(manager, monkeypatch):
    # Same guarantee without preload(): the first visit pays, the rest don't.
    counts = _count_constructions(monkeypatch, SoftwareView)

    for _ in range(20):
        manager.push_state(SoftwareState(manager))
        manager.pop_state()

    assert counts[SoftwareView] == 1


def test_every_visit_gets_the_same_view_instance(manager):
    views.preload(core_views())
    seen = set()

    for _ in range(5):
        state = SetupState(manager)
        manager.push_state(state)
        seen.add(id(state.view))
        manager.pop_state()

    assert len(seen) == 1


def test_the_view_is_released_so_the_next_visit_is_not_a_double_borrow(
    manager, caplog
):
    views.preload(core_views())

    with caplog.at_level("ERROR"):
        for _ in range(3):
            manager.push_state(SetupState(manager))
            manager.pop_state()

    assert "still borrowed" not in caplog.text


def test_stacking_setup_over_the_screen_below_does_not_share_a_view(manager, caplog):
    # push_state pauses rather than exits, so both states are live at once.
    # They must be holding different view classes.
    with caplog.at_level("ERROR"):
        manager.push_state(SoftwareState(manager))
        manager.push_state(SetupState(manager))

    assert "still borrowed" not in caplog.text
    assert manager._stack[0].view is not manager._stack[1].view


# --------------------------------------------------------------------------
# The shared background
# --------------------------------------------------------------------------
def test_every_state_shares_one_background_surface(manager):
    manager.push_state(SoftwareState(manager))
    below = manager.current_state.background

    manager.push_state(SetupState(manager))
    above = manager.current_state.background

    assert above is below, "the background is allocated once, not per entry"


def test_twenty_visits_allocate_one_background(manager, monkeypatch):
    original = pygame.Surface
    sizes = []

    def counting(size, *a, **kw):
        sizes.append(tuple(size))
        return original(size, *a, **kw)

    manager.push_state(SoftwareState(manager))  # allocate it before counting
    monkeypatch.setattr(pygame, "Surface", counting)

    for _ in range(20):
        manager.push_state(SetupState(manager))
        manager.pop_state()

    full_screen = [s for s in sizes if s == (1280, 720)]
    assert full_screen == [], f"per-transition full-screen surfaces: {full_screen}"


def test_a_covered_state_repaints_its_own_background_on_resume(manager):
    """The hazard one shared surface creates: Setup paints its chrome onto
    the surface Software is using as its dirty-rect restore source. Safe only
    because the state underneath re-derives it when it comes back."""
    software = SoftwareState(manager)
    manager.push_state(software)

    repainted = []
    original = software.draw_static_background
    software.draw_static_background = lambda bg: (
        repainted.append(bg), original(bg)
    )[1]

    manager.push_state(SetupState(manager))
    assert repainted == [], "still covered; nothing to repaint yet"

    manager.pop_state()

    assert repainted, "a resumed state must re-bake its static background"
    assert repainted[0] is software.background


def test_resuming_queues_a_full_repaint_of_the_screen(manager):
    manager.push_state(SoftwareState(manager))
    manager.push_state(SetupState(manager))
    manager.pop_state()

    assert manager._pending_rects == [manager._screen.get_rect()]
