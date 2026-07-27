import pygame
import pytest
from pygame.sprite import LayeredDirty

from instrument_cluster.ui.widgets.base.button import ButtonEvents
from instrument_cluster.ui.widgets.base.dropdown import Dropdown

DD_PRESSED = pygame.event.custom_type()
DD_RELEASED = pygame.event.custom_type()
DD_SELECTED = pygame.event.custom_type()

HEADER_POS = (120, 120)


@pytest.fixture
def dropdown():
    group = LayeredDirty()
    dd = Dropdown(
        rect=(100, 100, 400, 80),
        options=["Demo", "Gran Turismo 7"],
        events=ButtonEvents(
            pressed=DD_PRESSED,
            released=DD_RELEASED,
            selected=DD_SELECTED,
        ),
        selected_index=1,
    )
    group.add(dd)
    dd.bind_group(group)
    return dd


# Touch events carry coordinates normalized over the panel; mouse events
# would be normalized by the test's 1x1 dummy window instead, so fingers are
# the deterministic way to hit logical (1280x720) positions headlessly.
def _finger_event(event_type, pos):
    return pygame.event.Event(
        event_type, {"x": pos[0] / 1280, "y": pos[1] / 720, "finger_id": 1}
    )


def _tap(widget, pos):
    widget.handle_event(_finger_event(pygame.FINGERDOWN, pos))
    widget.handle_event(_finger_event(pygame.FINGERUP, pos))


def _drain_events():
    return pygame.event.get()


def test_header_tap_opens_the_menu(dropdown):
    _tap(dropdown, HEADER_POS)
    assert dropdown.open is True
    assert dropdown._menu_sprites


def test_second_header_tap_closes_without_firing_selected(dropdown):
    """Regression: tapping the open header used to re-fire `selected` with
    the current option, sending Setup into the feed's IP-entry flow."""
    _tap(dropdown, HEADER_POS)
    _drain_events()

    _tap(dropdown, HEADER_POS)

    assert dropdown.open is False
    assert [e for e in _drain_events() if e.type == DD_SELECTED] == []


def test_choosing_an_option_fires_selected_and_closes(dropdown):
    _tap(dropdown, HEADER_POS)
    _drain_events()

    option_rect = dropdown._menu_sprites[0].rect
    _tap(dropdown, option_rect.center)

    assert dropdown.open is False
    assert dropdown.selected_index == 0
    selected = [e for e in _drain_events() if e.type == DD_SELECTED]
    assert len(selected) == 1
    assert selected[0].selected_index == 0


# --- Per-option display labels ---------------------------------------------


def _labelled(labels=None, selected_index=0):
    from instrument_cluster.telemetry.mode import DiffReferenceMode
    from instrument_cluster.ui.widgets.base.button import ButtonEvents

    return Dropdown(
        rect=(0, 0, 300, 60),
        options=list(DiffReferenceMode),
        events=ButtonEvents(pressed=pygame.NOEVENT, released=pygame.NOEVENT),
        selected_index=selected_index,
        labels=labels,
    )


def test_without_labels_an_enum_option_shows_its_raw_value():
    """The pre-existing behaviour, still right for options that are already
    display strings (feed names)."""
    assert _labelled().text == "previous"


def test_labels_replace_the_header_text():
    from instrument_cluster.telemetry.mode import DiffReferenceMode

    dd = _labelled({m: m.label for m in DiffReferenceMode})
    assert dd.text == "Previous"


def test_labels_follow_a_selection_change():
    from instrument_cluster.telemetry.mode import DiffReferenceMode

    dd = _labelled({m: m.label for m in DiffReferenceMode})
    dd.set_selected_index(list(DiffReferenceMode).index(DiffReferenceMode.FASTEST))
    assert dd.text == "Fastest"


def test_labels_apply_to_the_open_menu_rows():
    from instrument_cluster.telemetry.mode import DiffReferenceMode

    dd = _labelled({m: m.label for m in DiffReferenceMode})
    rendered = [dd._label_for_value(v) for v in dd.options]
    assert rendered == ["Previous", "Fastest"]


def test_a_partial_label_map_falls_back_per_option():
    from instrument_cluster.telemetry.mode import DiffReferenceMode

    dd = _labelled({DiffReferenceMode.FASTEST: "Fastest"})
    rendered = [dd._label_for_value(v) for v in dd.options]
    assert rendered == ["previous", "Fastest"]
