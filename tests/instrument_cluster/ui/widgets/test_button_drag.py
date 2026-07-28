"""Button: a held press keeps its highlight, wherever the pointer goes.

Deliberate behaviour, not an oversight — motion events are not mapped to a
pointer id, so dragging off a held button leaves it lit. Only the release
decides whether the press counted. Tried the alternative (un-press on
drag-out, re-press on drag-back-in) and it was rejected as twitchy on a
touch panel.

What must *not* happen is the highlight surviving the release; that was a
real bug, and its cause was a transparent idle image rather than the state
machine — see test_feed_update_window.py.

Touch rather than mouse throughout: Display.to_logical divides mouse
coordinates by the display surface, which the test harness sets to 1x1, so
mouse positions land nowhere.
"""
import pygame
import pytest

from instrument_cluster.ui.utils import srect
from instrument_cluster.ui.widgets.base.button import (
    Button,
    ButtonEvents,
    ButtonState,
)

RECT = (390, 420, 220, 70)
INSIDE = (500, 455)
OUTSIDE = (100, 650)

PRESSED_EVENT = pygame.event.custom_type()
RELEASED_EVENT = pygame.event.custom_type()


@pytest.fixture
def button():
    return Button(
        rect=srect(*RECT),
        text="Update now",
        text_visible=True,
        events=ButtonEvents(pressed=PRESSED_EVENT, released=RELEASED_EVENT),
    )


def _send(button, kind, pos, finger_id=1):
    x, y = pos
    button.handle_event(
        pygame.event.Event(
            kind, {"x": x / 1280, "y": y / 720, "finger_id": finger_id}
        )
    )


def _released_posted():
    return any(e.type == RELEASED_EVENT for e in pygame.event.get())


def test_a_held_button_stays_lit_when_dragged_off(button):
    _send(button, pygame.FINGERDOWN, INSIDE)
    assert button.state is ButtonState.PRESSED

    _send(button, pygame.FINGERMOTION, OUTSIDE)

    assert button.state is ButtonState.PRESSED


def test_releasing_off_the_button_clears_it_and_does_not_count(button):
    """Dragging away is how you cancel — but only the release settles it."""
    pygame.event.clear()
    _send(button, pygame.FINGERDOWN, INSIDE)
    _send(button, pygame.FINGERMOTION, OUTSIDE)
    _send(button, pygame.FINGERUP, OUTSIDE)

    assert button.state is ButtonState.IDLE
    assert not _released_posted()


def test_releasing_on_the_button_counts(button):
    pygame.event.clear()
    _send(button, pygame.FINGERDOWN, INSIDE)
    _send(button, pygame.FINGERMOTION, OUTSIDE)
    _send(button, pygame.FINGERMOTION, INSIDE)
    _send(button, pygame.FINGERUP, INSIDE)

    assert button.state is ButtonState.RELEASED
    assert _released_posted()


def test_motion_alone_never_presses_a_button(button):
    """An unheld pointer sweeping the screen owns nothing."""
    _send(button, pygame.FINGERMOTION, INSIDE)
    assert button.state is ButtonState.IDLE
