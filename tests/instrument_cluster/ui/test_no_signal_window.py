"""NoSignalWindow — the SYSTEM_ALERT overlay for telemetry link loss.

The readers hold their last frame forever, so without this the gauges would
show the last speed and gear indefinitely, pixel-identical to live data.
"""
import pygame
import pytest

from instrument_cluster.ui.no_signal_window import (
    _banner_border,
    _banner_fill,
    NoSignalWindow,
    banner_rect,
    build_banner,
)

# The palette resolves at build time now (skin-editor live preview); the
# tests keep the old constant names as locals.
BANNER_TOP_COLOR, BANNER_BOTTOM_COLOR = _banner_fill()
BANNER_BORDER_TOP_COLOR, BANNER_BORDER_BOTTOM_COLOR = _banner_border()
from instrument_cluster.ui.utils import vertical_gradient
from instrument_cluster.ui.window_layering import WindowLayer, WindowManager


class _Bus:
    def __init__(self, stale=False):
        self.signals = {"telemetry_stale": stale}


class _State:
    """Stands in for DashboardState, which opts into system alerts."""

    allows_system_alert = True


class _PlainState:
    """A state that does not opt in (Setup, IP entry, install, wifi)."""


class _StateManager:
    def __init__(self, state):
        self.current_state = state
        self.is_running = True
        self.full_paints = 0

    def request_full_paint(self):
        self.full_paints += 1

    def draw(self, surface):
        return []

    def update(self, dt):
        pass

    def handle_event(self, event):
        return False


@pytest.fixture
def window():
    bus = _Bus()
    manager = _StateManager(_State())
    return NoSignalWindow(bus, manager), bus, manager


# --- Visibility -----------------------------------------------------------


def test_hidden_while_the_link_is_live(window):
    win, bus, _ = window
    assert win.visible is False


def test_shown_when_the_link_goes_stale(window):
    win, bus, _ = window
    bus.signals["telemetry_stale"] = True
    assert win.visible is True


def test_hidden_on_states_that_do_not_opt_in(window):
    """Setup is where a dead feed gets configured — covering it with the
    alert would obscure the remedy."""
    win, bus, manager = window
    bus.signals["telemetry_stale"] = True
    manager.current_state = _PlainState()
    assert win.visible is False


def test_sits_on_the_system_alert_layer(window):
    win, _, _ = window
    assert win.layer is WindowLayer.SYSTEM_ALERT
    assert win.layer > WindowLayer.NOTIFICATION


# --- Compositing ----------------------------------------------------------


def test_reappearing_redirties_its_sprite(window):
    """The banner image never changes, so its sprite would stay clean after
    the first paint and a second outage would composite nothing."""
    win, bus, _ = window
    bus.signals["telemetry_stale"] = True
    win.update(0.016)
    assert win.sprites[0].dirty == 1

    surface = pygame.Surface((1280, 720))
    win.draw(surface, [])
    assert win.sprites[0].dirty == 0

    bus.signals["telemetry_stale"] = False
    win.update(0.016)
    bus.signals["telemetry_stale"] = True
    win.update(0.016)

    assert win.sprites[0].dirty == 1, "must repaint on the next outage"


def test_draws_nothing_while_hidden(window):
    win, _, _ = window
    surface = pygame.Surface((1280, 720))
    assert win.draw(surface, []) == []


def test_composites_over_a_base_repaint(window):
    """A base dirty rect under the banner is re-covered by the compositor —
    the whole point of it being a window rather than something the view
    paints."""
    win, bus, _ = window
    bus.signals["telemetry_stale"] = True
    win.update(0.016)

    surface = pygame.Surface((1280, 720))
    win.draw(surface, [])
    win.sprites[0].dirty = 0

    rect = banner_rect()
    surface.fill((0, 255, 0), rect)  # base scribbles under the banner
    painted = win.draw(surface, [rect])

    assert painted, "the overlay must reclaim the region"
    assert surface.get_at(rect.center)[:3] != (0, 255, 0)


def test_disappearing_asks_the_base_to_repaint(window):
    """Otherwise the banner's pixels linger after recovery."""
    win, bus, manager = window
    manager_wm = WindowManager(manager)
    manager_wm.add_window(win)
    surface = pygame.Surface((1280, 720))

    bus.signals["telemetry_stale"] = True
    manager_wm.draw(surface)
    assert manager.full_paints == 0

    bus.signals["telemetry_stale"] = False
    manager_wm.draw(surface)
    assert manager.full_paints == 1


# --- Arbitration against the stale-feed notice ------------------------------
#
# Both windows can want the screen at the same time: a device whose feed
# predates the image (FeedUpdateWindow, NOTIFICATION) is also a plausible
# reason for the link to be dead (NoSignalWindow, SYSTEM_ALERT). Z-order
# alone drew both, overlapping.


def test_declares_that_it_occludes_below(window):
    win, _, _ = window
    assert win.occludes_below is True
    assert win.show_when_occluded is False


def test_the_banner_would_otherwise_overlap_the_notice_card():
    """Why occlusion, and not just leaving them stacked.

    The band is full width and the card is centred, so the two rects meet
    however either is laid out — the band cuts across the card's lower edge.
    """
    from instrument_cluster.ui.feed_update_window import _card_rect

    assert banner_rect().colliderect(_card_rect())


def _stale_feed_notice(state_manager):
    from instrument_cluster.config import Config
    from instrument_cluster.ui.feed_update_window import FeedUpdateWindow

    config = Config(
        telemetry_mode="udp",
        telemetry_feed="granturismo",
        telemetry_feed_version="v0.3.10",  # not the pinned build
    )
    win = FeedUpdateWindow(config, state_manager, (1280, 720))
    assert win.visible is True, "fixture must start with a notice to defer"
    return win


class _DashboardState(_State):
    """Opts into both — the only state where the two can collide."""

    allows_notification_popup = True


def test_a_dead_link_withdraws_the_stale_feed_notice(window):
    """The alert is read alone; the notice waits."""
    from instrument_cluster.ui.window_layering import WindowManager

    win, bus, manager = window
    manager.current_state = _DashboardState()
    notice = _stale_feed_notice(manager)
    wm = WindowManager(manager)
    wm.add_window(win)
    wm.add_window(notice)
    surface = pygame.Surface((1280, 720))

    bus.signals["telemetry_stale"] = True
    wm.update(0.016)
    wm.draw(surface)

    assert win.showing is True
    assert notice.showing is False
    assert notice.visible is True, "deferred, not dismissed"
    assert notice._dismissed is False


def test_the_notice_comes_back_when_the_link_recovers(window):
    """And actually repaints: its card and dimming are static sprites, so a
    return that forgot to re-dirty them would composite nothing."""
    from instrument_cluster.ui.feed_update_window import _card_color
    from instrument_cluster.ui.window_layering import WindowManager

    CARD_COLOR = _card_color()

    win, bus, manager = window
    manager.current_state = _DashboardState()
    notice = _stale_feed_notice(manager)
    wm = WindowManager(manager)
    wm.add_window(win)
    wm.add_window(notice)
    surface = pygame.Surface((1280, 720))

    bus.signals["telemetry_stale"] = True
    wm.update(0.016)
    wm.draw(surface)

    bus.signals["telemetry_stale"] = False
    wm.update(0.016)
    wm.draw(surface)

    assert notice.showing is True
    card = notice.sprites[1]
    assert surface.get_at(card.rect.center)[:3] == CARD_COLOR


def test_a_withdrawn_notice_stops_swallowing_touches(window):
    """It is modal while up — every pointer event — so leaving it wired up
    while off-screen would eat taps aimed at the Setup button underneath."""
    from instrument_cluster.ui.window_layering import WindowManager

    win, bus, manager = window
    manager.current_state = _DashboardState()
    notice = _stale_feed_notice(manager)
    wm = WindowManager(manager)
    wm.add_window(win)
    wm.add_window(notice)

    bus.signals["telemetry_stale"] = True
    wm.update(0.016)

    tap = pygame.event.Event(pygame.FINGERDOWN, {"x": 0.5, "y": 0.9})
    assert wm.handle_event(tap) is False, "must fall through to the base"
    assert notice.handle_event(tap) is False


# --- Appearance -----------------------------------------------------------


def test_banner_sits_in_the_free_strip_between_the_gauges_and_the_footer():
    """The band clears everything either side of it.

    The gear widget's rect ends at design y 504 and the footer's first ink is
    at 630, so the band lives strictly in that gap: eating into the gear digit
    would hide one of the very readings it marks as stale, and reaching the
    footer would hide the Setup button and lap counter — controls rather than
    a reading, and the Setup button is the route to the remedy.
    """
    from instrument_cluster.ui.utils import sy

    rect = banner_rect()
    assert rect.top >= sy(504), "must not cover the gear widget"
    assert rect.bottom <= sy(630), "must not reach the footer row"


def test_banner_uses_the_shared_panel_gradient():
    """Generated by the same ramp as the gauge panels (ui/utils), not a
    hand-rolled curve."""
    from instrument_cluster.ui.utils import su, vertical_gradient
    from instrument_cluster.ui.no_signal_window import BANNER_BORDER_WIDTH

    size = banner_rect().size
    banner = build_banner(size)
    expected = vertical_gradient(size, BANNER_TOP_COLOR, BANNER_BOTTOM_COLOR)

    width, height = size
    inset = max(1, su(BANNER_BORDER_WIDTH))
    x = width // 4  # clear of both the centred text and the rounded corners

    for y in range(inset, height - inset):
        assert banner.get_at((x, y))[:3] == expected.get_at((x, y))[:3]

    # A single ramp with no peak in the middle. Which way it runs is the two
    # constants' business — and the loop above already pins it to them — so
    # this only says the fill never doubles back on itself.
    ramp = [banner.get_at((x, y))[0] for y in range(inset, height - inset)]
    assert ramp == sorted(ramp) or ramp == sorted(ramp, reverse=True)


def test_banner_has_a_thin_border():
    size = banner_rect().size
    banner = build_banner(size)
    width, height = size
    x = width // 4

    assert banner.get_at((x, 0))[:3] == BANNER_BORDER_TOP_COLOR
    assert banner.get_at((x, height - 1))[:3] == BANNER_BORDER_BOTTOM_COLOR

    depth = 0
    while banner.get_at((x, depth))[:3] == BANNER_BORDER_TOP_COLOR:
        depth += 1
    assert 1 <= depth <= 4, f"border is {depth}px deep"


def test_border_ramps_from_quiet_to_loud():
    """The two rules do different jobs, so the border is a ramp not a colour.

    The bottom rule is the accent — the only colour in the widget, and what
    makes a neutral grey-to-black band read as an alert. The top rule only
    separates the band from the panel behind it, so it stays low-chroma: a
    second saturated line 100 px away would box the band in and split the eye
    between two reds.
    """

    def saturation(c):
        mx, mn = max(c), min(c)
        return 0.0 if mx == 0 else (mx - mn) / mx

    assert saturation(BANNER_BORDER_TOP_COLOR) < 0.2, (
        "the top rule must stay quiet — the accent is the bottom one"
    )
    assert saturation(BANNER_BORDER_BOTTOM_COLOR) > saturation(
        BANNER_BORDER_TOP_COLOR
    )
    # And it stays a visible step above the fill at both ends.
    assert BANNER_BORDER_TOP_COLOR != BANNER_TOP_COLOR
    assert BANNER_BORDER_BOTTOM_COLOR != BANNER_BOTTOM_COLOR


def test_banner_top_corners_are_rounded():
    """Cut out of the surface, not just outlined — a rounded outline over an
    opaque rect leaves square gradient pixels behind the arc."""
    size = banner_rect().size
    banner = build_banner(size)
    width, height = size

    assert banner.get_at((0, 0))[3] == 0
    assert banner.get_at((width - 1, 0))[3] == 0
    # The bottom corners stay square: the band meets the footer there.
    assert banner.get_at((0, height - 1))[3] == 255
    assert banner.get_at((width - 1, height - 1))[3] == 255
    assert banner.get_at((width // 2, 0))[3] == 255


def test_banner_has_no_side_borders():
    """Top and bottom rules only.

    The band is full width, so vertical sides would be hairlines hugging the
    screen edges — a box drawn around the panel rather than a rule across it.
    """
    from instrument_cluster.ui.utils import su
    from instrument_cluster.ui.no_signal_window import BANNER_BORDER_WIDTH

    size = banner_rect().size
    banner = build_banner(size)
    width, height = size
    bw = max(1, su(BANNER_BORDER_WIDTH))

    expected = vertical_gradient(size, BANNER_TOP_COLOR, BANNER_BOTTOM_COLOR)
    # Mid-height, hard against both edges: must be plain fill, not border.
    for x in (0, bw - 1, width - bw, width - 1):
        y = height // 2
        assert banner.get_at((x, y))[:3] == expected.get_at((x, y))[:3]

    # The horizontal rules still run the full width.
    assert banner.get_at((0, height - 1))[:3] == BANNER_BORDER_BOTTOM_COLOR
    assert banner.get_at((width - 1, height - 1))[:3] == BANNER_BORDER_BOTTOM_COLOR
