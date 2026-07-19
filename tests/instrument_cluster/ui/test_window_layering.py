"""WindowManager: automotive-style window layering.

The base layer (StateManager) keeps drawing live; overlay windows are
composited above it every frame. The regression this pins down: a base
widget redrawing underneath an overlay must never end up on top of it.
"""

from unittest.mock import MagicMock

import pygame
import pytest

from instrument_cluster.ui.window_layering import (
    OverlayWindow,
    WindowLayer,
    WindowManager,
)

CARD = pygame.Rect(100, 0, 400, 200)
CARD_COLOR = (40, 40, 40)
BASE_COLOR = (200, 0, 0)


def make_sprite(rect, color):
    sprite = pygame.sprite.DirtySprite()
    sprite.rect = pygame.Rect(rect)
    sprite.image = pygame.Surface(sprite.rect.size)
    sprite.image.fill(color)
    sprite.visible = 1
    sprite.dirty = 1
    return sprite


class CardWindow(OverlayWindow):
    layer = WindowLayer.NOTIFICATION

    def __init__(self):
        super().__init__()
        self.sprites = [make_sprite(CARD, CARD_COLOR)]
        self._visible = True

    @property
    def visible(self):
        return self._visible


@pytest.fixture
def surface():
    return pygame.Surface((1280, 720))


def make_manager(base_rects=()):
    """A WindowManager over a fake base that 'draws' the given dirty
    rects each frame (painting them in BASE_COLOR, like a live gauge)."""
    state_manager = MagicMock()

    def base_draw(surface):
        for rect in base_rects:
            surface.fill(BASE_COLOR, rect)
        return [pygame.Rect(r) for r in base_rects]

    state_manager.draw.side_effect = base_draw
    return WindowManager(state_manager), state_manager


def test_base_redraw_underneath_never_covers_the_overlay(surface):
    """A gauge repainting under the card must trigger a re-composite."""
    gauge_rect = pygame.Rect(150, 50, 100, 100)  # inside the card area
    manager, _ = make_manager(base_rects=[gauge_rect])
    window = CardWindow()
    manager.add_window(window)

    manager.draw(surface)  # first frame: overlay dirty, draws
    manager.draw(surface)  # gauge redraws under the card -> re-composite

    assert surface.get_at(gauge_rect.center)[:3] == CARD_COLOR


def test_untouched_overlay_is_not_redrawn(surface):
    manager, _ = make_manager(base_rects=[pygame.Rect(700, 500, 50, 50)])
    window = CardWindow()
    manager.add_window(window)

    manager.draw(surface)  # first frame: overlay draws (dirty)
    rects = manager.draw(surface)  # disjoint base rect: no re-composite

    assert CARD not in rects


def test_translucent_overlay_never_compounds_its_dimming(surface):
    """A dim scrim must darken a pixel exactly once, not once per frame.

    Regression: re-blitting the whole stack whenever the base drew
    anywhere kept re-dimming pixels the base had NOT repainted, so
    low-rate widgets faded to black between their repaints (flicker).
    """

    class ScrimWindow(CardWindow):
        def __init__(self):
            super().__init__()
            scrim = pygame.sprite.DirtySprite()
            scrim.rect = pygame.Rect(0, 0, 1280, 720)
            scrim.image = pygame.Surface(scrim.rect.size, pygame.SRCALPHA)
            scrim.image.fill((0, 0, 0, 128))
            scrim.visible = 1
            scrim.dirty = 1
            self.sprites = [scrim]

    gauge_rect = pygame.Rect(200, 400, 100, 100)  # repaints every frame
    static_px = (700, 600)  # base content the base never repaints
    manager, _ = make_manager(base_rects=[gauge_rect])
    manager.add_window(ScrimWindow())
    surface.fill((200, 200, 200))

    manager.draw(surface)  # scrim dirty: dims the whole screen once
    static_after_show = surface.get_at(static_px)[:3]
    manager.draw(surface)
    gauge_frame2 = surface.get_at(gauge_rect.center)[:3]
    manager.draw(surface)

    # The un-repainted pixel was dimmed exactly once, ever...
    assert surface.get_at(static_px)[:3] == static_after_show
    # ...and the live gauge pixel is stable frame-over-frame (repainted
    # bright by the base, then dimmed exactly once per frame).
    assert surface.get_at(gauge_rect.center)[:3] == gauge_frame2
    assert gauge_frame2 != BASE_COLOR  # but it *is* dimmed


def test_hiding_an_overlay_repaints_the_base(surface):
    manager, state_manager = make_manager()
    window = CardWindow()
    manager.add_window(window)

    manager.draw(surface)
    window._visible = False
    manager.draw(surface)

    state_manager.request_full_paint.assert_called_once()


def test_overlays_get_events_before_the_base():
    manager, state_manager = make_manager()
    window = CardWindow()
    window.handle_event = MagicMock(return_value=True)
    manager.add_window(window)

    assert manager.handle_event(pygame.event.Event(pygame.USEREVENT)) is True
    state_manager.handle_event.assert_not_called()


def test_unconsumed_events_reach_the_base():
    manager, state_manager = make_manager()
    manager.add_window(CardWindow())
    state_manager.handle_event.return_value = False

    manager.handle_event(pygame.event.Event(pygame.USEREVENT))

    state_manager.handle_event.assert_called_once()


def test_windows_composite_in_layer_order(surface):
    order = []

    class Recorder(CardWindow):
        def __init__(self, layer, name):
            super().__init__()
            self.layer = layer
            self._name = name

        def draw(self, surface, below_rects):
            order.append(self._name)
            return super().draw(surface, below_rects)

    manager, _ = make_manager()
    manager.add_window(Recorder(WindowLayer.SYSTEM_ALERT, "alert"))
    manager.add_window(Recorder(WindowLayer.NOTIFICATION, "notification"))

    manager.draw(surface)

    assert order == ["notification", "alert"]
