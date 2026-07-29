"""WindowManager: automotive-style window layering.

The base layer (StateManager) keeps drawing live; overlay windows are
composited above it every frame. The regression this pins down: a base
widget redrawing underneath an overlay must never end up on top of it.

The second half covers arbitration — which of two windows that both want
to be up actually is. Layers settle pixels; arbitration settles presence.
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


# --- Arbitration ----------------------------------------------------------
#
# The gap this closes: a NOTIFICATION card up, then a SYSTEM_ALERT arrives.
# Z-order alone draws both, overlapping. AAOS withdraws the lower window
# instead (OverlayViewGlobalStateController's occlusion set) and restores it
# afterwards, which is what these pin down.

ALERT = pygame.Rect(0, 150, 1280, 100)
ALERT_COLOR = (0, 0, 255)


class AlertWindow(OverlayWindow):
    """Stands in for NoSignalWindow: topmost, and read alone."""

    layer = WindowLayer.SYSTEM_ALERT
    occludes_below = True

    def __init__(self):
        super().__init__()
        self.sprites = [make_sprite(ALERT, ALERT_COLOR)]
        self._visible = True

    @property
    def visible(self):
        return self._visible


def make_pair(base_rects=()):
    """A card on NOTIFICATION and an alert on SYSTEM_ALERT, both wanting up.

    Registered alert-first on purpose: arbitration must depend on the layer,
    not on which one was added or lit up first.
    """
    manager, state_manager = make_manager(base_rects=base_rects)
    alert, card = AlertWindow(), CardWindow()
    manager.add_window(alert)
    manager.add_window(card)
    return manager, state_manager, alert, card


def frame(manager, surface):
    manager.update(1 / 60)
    return manager.draw(surface)


def test_both_stay_up_when_nothing_occludes(surface):
    """The default is unchanged behaviour: two overlays co-exist."""
    manager, _, alert, card = make_pair()
    alert.occludes_below = False

    frame(manager, surface)

    assert alert.showing is True
    assert card.showing is True


def test_the_topmost_occluder_withdraws_the_window_below(surface):
    manager, _, alert, card = make_pair()

    frame(manager, surface)

    assert alert.showing is True
    assert card.visible is True, "the card still wants to be up"
    assert card.occluded is True
    assert card.showing is False


def test_a_withdrawn_window_is_not_composited(surface):
    """Not drawn, not merely covered — the distinction the whole thing rests
    on. The card's rect is checked where the alert does *not* overlap it."""
    manager, _, alert, card = make_pair()
    clear_of_alert = (CARD.centerx, CARD.top + 10)
    assert not ALERT.collidepoint(clear_of_alert)
    surface.fill((0, 0, 0))

    frame(manager, surface)

    assert surface.get_at(clear_of_alert)[:3] != CARD_COLOR
    assert surface.get_at(ALERT.center)[:3] == ALERT_COLOR


def test_a_lower_layer_cannot_withdraw_a_higher_one(surface):
    """Only the topmost visible window is asked whether it occludes.

    Otherwise a notification card could suppress a safety alert, which is
    exactly what the layer ordering exists to forbid.
    """
    manager, _, alert, card = make_pair()
    card.occludes_below = True
    alert.occludes_below = False

    frame(manager, surface)

    assert alert.showing is True, "an alert must never be withdrawn"
    assert card.showing is True


def test_show_when_occluded_survives_an_occluder(surface):
    manager, _, alert, card = make_pair()
    card.show_when_occluded = True

    frame(manager, surface)

    assert card.showing is True
    assert surface.get_at((CARD.centerx, CARD.top + 10))[:3] == CARD_COLOR


def test_a_withdrawn_window_returns_when_the_occluder_goes(surface):
    """Deferral, never dismissal: nothing latches, so the card comes back on
    its own — the AAOS restore-from-the-occlusion-set behaviour."""
    manager, _, alert, card = make_pair()

    frame(manager, surface)
    assert card.showing is False

    alert._visible = False
    frame(manager, surface)

    assert card.occluded is False
    assert card.showing is True
    assert surface.get_at(CARD.center)[:3] == CARD_COLOR, "and it repaints"


def test_withdrawing_a_window_repaints_the_base(surface):
    """Its pixels are just as stale as if it had hidden itself."""
    manager, state_manager, alert, card = make_pair()
    alert._visible = False

    frame(manager, surface)  # card up alone
    assert state_manager.request_full_paint.call_count == 0

    alert._visible = True
    frame(manager, surface)  # alert arrives, card withdrawn

    state_manager.request_full_paint.assert_called_once()


def test_a_withdrawn_window_gets_no_events(surface):
    """A modal that is no longer on screen must not still be swallowing
    taps — FeedUpdateWindow swallows every pointer event while it is up."""
    manager, state_manager, alert, card = make_pair()
    card.handle_event = MagicMock(return_value=True)
    state_manager.handle_event.return_value = False

    frame(manager, surface)
    manager.handle_event(pygame.event.Event(pygame.FINGERDOWN))

    card.handle_event.assert_not_called()
    state_manager.handle_event.assert_called_once()


def test_arbitration_precedes_the_windows_own_update(surface):
    """Windows key their dirty-sprite bookkeeping off the arbitrated answer,
    so they must not be asked before it is known."""
    seen = []

    class Probe(CardWindow):
        def update(self, dt):
            seen.append(self.occluded)

    manager, _ = make_manager()
    manager.add_window(AlertWindow())
    probe = Probe()
    manager.add_window(probe)

    manager.update(1 / 60)

    assert seen == [True]


def test_arbitration_does_not_latch_on_a_draw_only_loop(surface):
    """Some callers (previews, tests) drive draw() without update()."""
    manager, _, alert, card = make_pair()

    manager.draw(surface)
    assert card.showing is False

    alert._visible = False
    manager.draw(surface)
    assert card.showing is True
