"""NoSignalWindow — the SYSTEM_ALERT overlay for telemetry link loss.

The readers hold their last frame forever, so without this the gauges would
show the last speed and gear indefinitely, pixel-identical to live data.
"""
import pygame
import pytest

from instrument_cluster.ui.no_signal_window import (
    PILL_TEXT,
    NoSignalWindow,
    build_no_telemetry_pill,
)
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
    """The pill image never changes, so its sprite would stay clean after
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
    """A base dirty rect under the pill is re-covered by the compositor —
    the whole point of it being a window rather than something the view
    paints."""
    win, bus, _ = window
    bus.signals["telemetry_stale"] = True
    win.update(0.016)

    surface = pygame.Surface((1280, 720))
    win.draw(surface, [])
    win.sprites[0].dirty = 0

    rect = win.sprites[0].rect
    surface.fill((0, 255, 0), rect)  # base scribbles under the pill
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
#
# The alert renders as the shared status pill (ui/status_pill.py) — the same
# shape and colours the Wi-Fi connecting note uses — so its look is pinned
# by sharing one builder rather than by pixel tests here. What this window
# owns is its wording.


def test_alert_is_the_shared_status_pill():
    """Pixel-identical to the shared builder fed the alert's text and the
    same border color the Wi-Fi pill uses — a red accent was tried and
    dropped, so the wording alone carries the alert."""
    from instrument_cluster.ui.skins import active_skin
    from instrument_cluster.ui.status_pill import build_pill

    alert = build_no_telemetry_pill()
    border = active_skin().overlays.wifi_pill_border_color
    expected = build_pill(PILL_TEXT, border)

    assert alert.rect == expected.rect
    assert (
        pygame.image.tostring(alert.image, "RGBA")
        == pygame.image.tostring(expected.image, "RGBA")
    )


def test_the_wording_names_the_missing_feed():
    """"No Telemetry" says what is gone; "no signal" read like a display or
    input problem. The trailing dots read as an ongoing wait, not a
    verdict."""
    assert PILL_TEXT == "No Telemetry ..."


def test_pill_sits_in_the_free_strip_between_the_gauges_and_the_footer():
    """The pill clears everything either side of it.

    The gear widget's rect ends at design y 504 and the footer's first ink is
    at 630, so the pill lives strictly in that gap: eating into the gear digit
    would hide one of the very readings it marks as stale, and reaching the
    footer would hide the Setup button and lap counter — controls rather than
    a reading, and the Setup button is the route to the remedy.
    """
    from instrument_cluster.ui.utils import sy

    rect = build_no_telemetry_pill().rect
    assert rect.top >= sy(504), "must not cover the gear widget"
    assert rect.bottom <= sy(630), "must not reach the footer row"
