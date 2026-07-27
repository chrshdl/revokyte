"""The NO SIGNAL alert — a composited SYSTEM_ALERT overlay window.

Telemetry link loss is exactly what the topmost overlay layer is for. Making
it a window rather than something ``DashboardView`` paints buys two things
the view could not give it:

* nothing can draw over it. A widget repainting under the banner is
  re-composited beneath it by the WindowManager, instead of the view having
  to restamp the band whenever a dirty rect wandered into it;
* the base keeps running live underneath, and the compositor already knows
  to repaint the base when the window disappears — so clearing the banner on
  recovery is no longer the view's problem either.

Visibility is driven by ``LinkSignal``'s ``telemetry_stale`` (see
``signals/link_signal.py``), gated on the active state opting in, the same
way notification popups are.
"""

from __future__ import annotations

import pygame

from ..peripherals.display import DESIGN_WIDTH
from ..signals.signal_keys import SignalKey
from .colors import Color
from .utils import FontFamily, load_font, su, sx, sy, vertical_gradient
from .window_layering import OverlayWindow, WindowLayer

# Banner geometry, in design px (topleft, w, h). Full width, in the strip
# between the Track Name / Previous Lap row and the footer — not along the
# top edge, which would sit on top of the Fastest Lap and Speed gauges. The
# banner must not hide the very readings it is marking as stale.
#
# It runs from 480 to 628, deliberately overlapping the gear widget: that
# widget's rect ends at 504 and its glyph ink at 489, so the band eats the
# empty padding plus the last ~9 px of the digit. It reads as a layered
# alert rather than a clipped glyph because of the border and rounded top.
# The bottom stops 2 px clear of the footer row, whose first ink is at 630.
BANNER_RECT = (0, 480, DESIGN_WIDTH, 148)
BANNER_TEXT = "NO SIGNAL"
BANNER_FONT_SIZE = 64
BANNER_FONT_FAMILY = FontFamily.D_DIN_EXP_BOLD

# Same ramp *and* the same colours the gauge panels use (see
# ui/utils.vertical_gradient and the tyre temp widget): dark at the top
# falling to RPM red at the bottom. A fully-saturated red-to-red pair was
# tried and rejected — the dark top is what ties the band to the rest of the
# dash, even though it costs saturation in the upper half.
BANNER_TOP_COLOR = Color.DARKEST_GREY.rgb()
BANNER_BOTTOM_COLOR = Color.RPM_RED.rgb()

# Thin outline so the band has a defined edge instead of bleeding into the
# panel. It ramps with the fill rather than being one flat colour: a solid
# red hairline sits at maximum chroma contrast against the near-black top
# edge — saturated red on black has no luminance edge for the eye to focus
# on, so a 1280 px line of it shimmers — while simultaneously vanishing into
# the red at the bottom. Ramping keeps the edge a constant, quiet step above
# the band the whole way down.
BANNER_BORDER_TOP_COLOR = Color.GREY.rgb()
BANNER_BORDER_BOTTOM_COLOR = Color.LIGHT_RED.rgb()
BANNER_BORDER_WIDTH = 2

# Rounded on the top corners only — the band runs to the bottom of the free
# strip, so its lower corners sit against the footer and reading square is
# right there. The corners are cut out of the surface rather than merely
# outlined, or the gradient would still square them off behind the arc.
BANNER_CORNER_RADIUS = 2

# Mask values, not colours. The mask is multiplied into the gradient
# (BLEND_RGB_MULT), so the opaque value has to be the identity multiplier —
# 255, not Color.WHITE, which is (210, 210, 210) and would darken the whole
# band by ~18%. The clear value only needs alpha 0; its RGB is irrelevant,
# so it takes the palette's black.
_MASK_OPAQUE = (255, 255, 255, 255)
_MASK_CLEAR = (*Color.BLACK.rgb(), 0)


def banner_rect() -> pygame.Rect:
    """Screen-space rect of the banner."""
    x, y, w, h = BANNER_RECT
    return pygame.Rect(sx(x), sy(y), sx(w), sy(h))


def build_banner(size: tuple[int, int]) -> pygame.Surface:
    """Gradient band, rounded at the top, with the warning text centred."""
    width, height = size
    radius = max(1, su(BANNER_CORNER_RADIUS))

    # Mask first: opaque where the band shows, clear outside the rounded top
    # corners. Multiplying the gradient through it keeps those corners
    # transparent, so the panel behind shows and the radius actually reads
    # instead of being an arc drawn over square pixels.
    banner = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(
        banner,
        _MASK_OPAQUE,
        banner.get_rect(),
        border_top_left_radius=radius,
        border_top_right_radius=radius,
    )
    banner.blit(
        vertical_gradient(size, BANNER_TOP_COLOR, BANNER_BOTTOM_COLOR),
        (0, 0),
        special_flags=pygame.BLEND_RGB_MULT,
    )

    font = load_font(size=BANNER_FONT_SIZE, family=BANNER_FONT_FAMILY)
    text = font.render(BANNER_TEXT, True, Color.WHITE.rgb())
    banner.blit(text, text.get_rect(center=(width // 2, height // 2)))

    # Drawn last so nothing can paint over the edge. The band is full width,
    # so the left/right sides land on the screen edges and it reads as a top
    # and bottom rule. Same mask trick as the corners: the outline is drawn
    # opaque, then its own gradient is multiplied through it.
    width_px = max(1, su(BANNER_BORDER_WIDTH))
    outline = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(
        outline,
        _MASK_OPAQUE,
        outline.get_rect(),
        width_px,
        border_top_left_radius=radius,
        border_top_right_radius=radius,
    )

    # Strip the vertical sides, keeping the rounded top corners. The band is
    # full width, so the sides would be hairlines hugging the screen edges —
    # that reads as a box drawn around the panel instead of a rule across it.
    side = pygame.Rect(0, radius, width_px, height - radius - width_px)
    outline.fill(_MASK_CLEAR, side)
    outline.fill(_MASK_CLEAR, side.move(width - width_px, 0))

    outline.blit(
        vertical_gradient(size, BANNER_BORDER_TOP_COLOR, BANNER_BORDER_BOTTOM_COLOR),
        (0, 0),
        special_flags=pygame.BLEND_RGB_MULT,
    )
    banner.blit(outline, (0, 0))
    return banner


class NoSignalWindow(OverlayWindow):
    """Shows the NO SIGNAL band while the telemetry link is dead."""

    layer = WindowLayer.SYSTEM_ALERT

    def __init__(self, vehicle_bus, state_manager):
        super().__init__()
        self._bus = vehicle_bus
        self._state_manager = state_manager

        rect = banner_rect()
        sprite = pygame.sprite.DirtySprite()
        sprite.image = build_banner(rect.size)
        sprite.rect = rect
        sprite.visible = 1
        sprite.dirty = 1
        self.sprites = [sprite]

        self._was_visible = False

    @property
    def visible(self) -> bool:
        if not self._bus.signals.get(SignalKey.TELEMETRY_STALE):
            return False
        # Only over the dashboard. Covering Setup — where the feed is
        # configured, i.e. where someone goes to *fix* a dead link — would
        # obscure the remedy. Same duck-typed opt-in as notification popups.
        state = self._state_manager.current_state
        return bool(getattr(state, "allows_system_alert", False))

    def update(self, dt: float) -> None:
        # The banner image never changes, so its sprite would stay clean
        # after the first paint and a later reappearance would composite
        # nothing. Re-dirty it on the rising edge of visibility.
        now = self.visible
        if now and not self._was_visible:
            for sprite in self.sprites:
                sprite.dirty = 1
        self._was_visible = now
