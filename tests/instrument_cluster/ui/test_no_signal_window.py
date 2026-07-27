"""NoSignalWindow — the SYSTEM_ALERT overlay for telemetry link loss.

The readers hold their last frame forever, so without this the gauges would
show the last speed and gear indefinitely, pixel-identical to live data.
"""
import pygame
import pytest

from instrument_cluster.ui.no_signal_window import (
    BANNER_BORDER_BOTTOM_COLOR,
    BANNER_BORDER_TOP_COLOR,
    BANNER_BOTTOM_COLOR,
    BANNER_TOP_COLOR,
    NoSignalWindow,
    banner_rect,
    build_banner,
)
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


# --- Appearance -----------------------------------------------------------


def test_banner_overlaps_the_gear_widget_but_clears_the_footer():
    """Overlapping the gear widget is intended — it reads as a layered alert.

    The footer is not negotiable though: its first ink is at design y 630,
    and covering the Setup button or lap counter would hide controls rather
    than a reading.
    """
    from instrument_cluster.ui.utils import sy

    rect = banner_rect()
    assert rect.top < sy(504), "expected to overlap the gear widget's rect"
    # May clip the tail of the glyph (ink ends at 489), but only a little.
    assert rect.top >= sy(475)
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

    reds = [banner.get_at((x, y))[0] for y in range(inset, height - inset)]
    assert reds == sorted(reds), "a single top-to-bottom ramp, no peak"


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
    """The border tracks the fill instead of being one flat colour.

    A saturated red hairline on the near-black top edge has no luminance
    edge for the eye to focus on, so 1280 px of it shimmers. The top of the
    border therefore has to stay low-chroma, and only the bottom — where the
    fill is already red — carries the colour.
    """

    def saturation(c):
        mx, mn = max(c), min(c)
        return 0.0 if mx == 0 else (mx - mn) / mx

    assert saturation(BANNER_BORDER_TOP_COLOR) < 0.2, (
        "the top border must not be a saturated hairline against the "
        "near-black fill"
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
