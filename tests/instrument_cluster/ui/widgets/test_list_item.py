import pygame

from instrument_cluster.ui.widgets.base.list_item import ListItem
from instrument_cluster.ui.widgets.settings.brightness_widget import BrightnessWidget


class _Box:
    """Bare stand-in widget: just a rect authored in row-local coordinates."""

    def __init__(self, rect):
        self.rect = pygame.Rect(rect)


def test_places_children_at_row_position():
    box = _Box((570, 0, 440, 80))
    ListItem(y=150, widgets=[box])
    assert box.rect.topleft == (570, 150)


def test_row_x_offsets_children():
    box = _Box((0, 0, 100, 50))
    ListItem(y=200, widgets=[box], x=40)
    assert box.rect.topleft == (40, 200)


def test_nested_container_children_follow_the_row():
    brightness = BrightnessWidget(x=600)
    ListItem(y=244, widgets=[brightness])

    # buttons sit 2px into the row band (76px centered in 80px)
    assert brightness.minus_button.rect.topleft == (600, 246)
    assert brightness.plus_button.rect.topleft == (1034, 246)
    assert brightness.percent_label.rect.center == (855, 286)


def test_brightness_widget_set_percent_updates_label():
    brightness = BrightnessWidget()
    brightness.set_percent(70)
    assert brightness.percent_label.text == "70 %"
