"""The shared status pill — one look for the small overlay notes.

The Wi-Fi connecting pill and the no-telemetry alert are the same kind of
message: a short line the driver glances at, centred in the free strip the
dashboard leaves between the widget rows (see no_signal_window.py for why
that strip). One builder keeps them pixel-identical — same geometry, fill,
border, font and radius from the skin's ``wifi_pill_*`` group — so the two
read as a family rather than two inventions. Only the wording differs.
"""

from __future__ import annotations

import pygame

from .colors import Color
from .skins import active_skin
from .utils import FontFamily, load_font_px

PILL_BORDER_WIDTH = 2
PILL_BG_ALPHA = 235


def _pill_bg() -> tuple[int, int, int, int]:
    # Resolved at build time (not module scope) so palette overrides
    # (skin editor) reach a rebuilt pill.
    return (*Color.DARKER_GREY.rgb(), PILL_BG_ALPHA)


def build_pill(text: str, border_color_name: str) -> pygame.sprite.DirtySprite:
    """A ready-to-composite pill sprite, centred at the skin's pill spot."""
    skin = active_skin()
    o = skin.overlays
    font = load_font_px(o.wifi_pill_font, FontFamily[o.wifi_pill_font_family])
    border_color = Color[border_color_name].rgb()
    rendered = font.render(text, True, Color.WHITE.rgb())

    width = rendered.get_width() + 2 * o.wifi_pill_pad_x
    height = o.wifi_pill_height
    radius = height // 2

    image = pygame.Surface((width, height), pygame.SRCALPHA)
    pygame.draw.rect(image, _pill_bg(), image.get_rect(), border_radius=radius)
    pygame.draw.rect(
        image,
        border_color,
        image.get_rect(),
        width=PILL_BORDER_WIDTH,
        border_radius=radius,
    )
    image.blit(rendered, rendered.get_rect(center=image.get_rect().center))

    sprite = pygame.sprite.DirtySprite()
    sprite.image = image
    sprite.rect = image.get_rect(center=(skin.width // 2, o.wifi_pill_center_y))
    sprite.visible = 1
    sprite.dirty = 1
    return sprite
