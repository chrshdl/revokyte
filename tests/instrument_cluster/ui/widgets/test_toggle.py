import pygame
import pytest

from instrument_cluster.ui.widgets.base.button import ButtonEvents
from instrument_cluster.ui.widgets.base.toggle import Toggle

TOGGLE_PRESSED = pygame.event.custom_type()
TOGGLE_RELEASED = pygame.event.custom_type()
TOGGLE_SELECTED = pygame.event.custom_type()


@pytest.fixture
def toggle():
    return Toggle(
        rect=(100, 100, 400, 80),
        events=ButtonEvents(
            pressed=TOGGLE_PRESSED,
            released=TOGGLE_RELEASED,
            selected=TOGGLE_SELECTED,
        ),
        checked=False,
    )


# Touch events carry coordinates normalized over the panel; mouse events
# would be normalized by the test's 1x1 dummy window instead, so fingers are
# the deterministic way to hit logical (1280x720) positions headlessly.
def _finger_event(event_type, pos):
    return pygame.event.Event(
        event_type, {"x": pos[0] / 1280, "y": pos[1] / 720, "finger_id": 1}
    )


def _click(widget, pos):
    widget.handle_event(_finger_event(pygame.FINGERDOWN, pos))
    widget.handle_event(_finger_event(pygame.FINGERUP, pos))


def _drain_events():
    return pygame.event.get()


def test_tap_anywhere_in_rect_flips_state_and_fires_selected(toggle):
    _drain_events()
    _click(toggle, (120, 120))  # far from the right-aligned pill

    assert toggle.checked is True
    selected = [e for e in _drain_events() if e.type == TOGGLE_SELECTED]
    assert len(selected) == 1
    assert selected[0].checked is True

    _click(toggle, (120, 120))
    assert toggle.checked is False
    selected = [e for e in _drain_events() if e.type == TOGGLE_SELECTED]
    assert selected[0].checked is False


def test_release_outside_cancels_without_flipping(toggle):
    _drain_events()
    toggle.handle_event(_finger_event(pygame.FINGERDOWN, (120, 120)))
    toggle.handle_event(_finger_event(pygame.FINGERUP, (1100, 650)))

    assert toggle.checked is False
    assert [e for e in _drain_events() if e.type == TOGGLE_SELECTED] == []


def test_set_checked_without_fire_posts_no_event(toggle):
    _drain_events()
    toggle.set_checked(True)

    assert toggle.checked is True
    assert [e for e in _drain_events() if e.type == TOGGLE_SELECTED] == []


def test_set_checked_same_value_is_a_noop(toggle):
    _drain_events()
    toggle.set_checked(False, fire_event=True)

    assert toggle.checked is False
    assert [e for e in _drain_events() if e.type == TOGGLE_SELECTED] == []


def test_checked_state_changes_the_rendered_image(toggle):
    off_image = pygame.image.tobytes(toggle.image, "RGBA")
    toggle.set_checked(True)
    on_image = pygame.image.tobytes(toggle.image, "RGBA")

    assert off_image != on_image
