from abc import ABC, abstractmethod

import pygame
from pygame.sprite import DirtySprite

from ...core.vehicle.vehicle_bus import VehicleBus
from ..colors import Color
from ..skins import active_skin
from ..utils import FontFamily, load_font_px, vertical_gradient

# Spec-space (1280x720) header caption size, used when no explicit
# header_font_size is given: the custom-dashboard path authors in spec
# space and its font_scale carries both the rect ratio and the panel scale
# (see registry.py). Skinned construction passes the active skin's
# style.header_font_size instead.
_SPEC_HEADER_FONT_SIZE = 32


class Widget(DirtySprite, ABC):
    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str,
        anchor: str = "center",  # "topleft" or "center"
        header_margin: int | None = None,  # brings `header_text` down by x px
        font_value_size: int = 32,
        font_value_family: FontFamily | None = None,
        show_border: bool = True,
        antialias: bool = True,
        *,
        header_font_size: int | None = None,
        bg_color: tuple[int, int, int] | None = None,
        text_color: tuple[int, int, int] | None = None,
        # Custom-layout text color for the *value only* — the header
        # always renders in text_color (white). None keeps text_color.
        value_color: tuple[int, int, int] | None = None,
        border_color: tuple[int, int, int] | None = None,
        border_width: int | None = None,
        border_radius: int | None = None,
        bg_gradient_top: tuple[int, int, int] | None = None,
        bg_gradient_bottom: tuple[int, int, int] | None = None,
        font_scale: float = 1.0,
    ):
        super().__init__()
        style = active_skin().style
        px, py, self.w, self.h = rect

        # place widget based on anchor
        if anchor == "center":
            tlx = px - self.w // 2
            tly = py - self.h // 2
        elif anchor == "topleft":
            tlx = px
            tly = py
        else:
            raise ValueError(f"Unsupported anchor: {anchor}")

        # Typography follows the widget's size: custom dashboard layouts
        # build widgets at arbitrary rects with font_scale = (rect size /
        # spec size) * panel scale, so a resized gauge reads proportionally —
        # matching the builder's stretched preview. 1.0 everywhere else;
        # sizes are then native pixels straight from the skin.
        self.font_scale = float(font_scale)
        font_value_size = max(1, round(font_value_size * self.font_scale))
        if header_font_size is None:
            header_font_size = max(
                1, round(_SPEC_HEADER_FONT_SIZE * self.font_scale)
            )
        header_family = FontFamily[style.header_font_family]
        self.font_header = load_font_px(header_font_size, header_family)
        if font_value_family is None:
            font_value_family = FontFamily.D_DIN_EXP_BOLD
        self.font_value = load_font_px(font_value_size, font_value_family)
        self.font_value_size = font_value_size
        self.header_text = header_text
        self.value_offset_y = style.value_offset_y
        # Colors resolve at construction (not signature defaults): the
        # skin says *which* palette color each role wears, and a rebuilt
        # view sees live palette overrides (skin editor).
        self.bg_color = (
            Color[style.bg_color].rgb() if bg_color is None else bg_color
        )
        self.text_color = (
            Color[style.text_color].rgb() if text_color is None else text_color
        )
        self.value_color = value_color
        self.header_margin = (
            style.header_margin if header_margin is None else header_margin
        )
        self.antialias = antialias

        # create gradient surface or None
        self._bg_gradient_surface = self._create_background_gradient(
            bg_gradient_top,
            bg_gradient_bottom,
        )

        # decide border color
        if border_color is not None:
            self.border_color = border_color
        elif bg_gradient_top is not None:
            # reuse top gradient color as border
            self.border_color = bg_gradient_bottom
        else:
            self.border_color = Color[style.border_color].rgb()

        self.border_width = (
            style.border_width if border_width is None else border_width
        )
        self.border_radius = (
            style.border_radius if border_radius is None else border_radius
        )
        self.show_border = show_border

        self.image = pygame.Surface((self.w, self.h), pygame.SRCALPHA).convert_alpha()
        self.rect = self.image.get_rect(topleft=(tlx, tly))

        self._last_value_str = None
        # Raw input of the last set_value call. Widgets whose value changes
        # rarely compare against it to skip re-formatting entirely; a None
        # _last_value_str (initial state, or invalidated after set_header)
        # overrides the skip so the value is repainted onto the fresh base.
        self._last_raw_value = None
        self.digit_gap = style.digit_gap

        # cache for digits keyed by
        # (font_id, antialias, color, chars, punct_scale)
        self._digit_cache: dict[tuple, dict] = {}

        self._render_border_and_header()
        self._refresh_base_image()
        self.visible = 1
        # One-shot repaint (LayeredDirty resets it to 0 after drawing), then
        # repaint only on set_value change. Every screen handover — state
        # push/pop, overlay disappearing, page slide, window expose/resize —
        # goes through full_paint()/request_full_paint(), which re-dirties
        # every sprite, so a static widget can't be lost to a background
        # overwrite the way the always-dirty era worked around.
        self.dirty = 1

    def _render_border_and_header(self):
        self._fill_background()

        if self.show_border:
            pygame.draw.rect(
                self.image,
                self.border_color,
                self.image.get_rect(),
                self.border_width,
                self.border_radius,
            )

        # An empty header reserves nothing. render("") still returns a surface
        # a full font-height tall, so taking its rect unconditionally gave
        # header-less widgets a ~26px dead band at the top and pushed their
        # content down into the bottom border — on a short widget that clipped
        # the last rows off entirely. Only a header that draws costs height.
        if self.header_text:
            header_surf = self.font_header.render(
                self.header_text, False, self.text_color
            )
            header_rect = header_surf.get_rect(midtop=(self.w // 2, self.header_margin))
            self.image.blit(header_surf, header_rect)
            self._header_bottom = header_rect.bottom
        else:
            self._header_bottom = 0

    def set_header(self, header_text: str) -> None:
        """Change the header text and rebuild the cached base image.

        The fresh base holds only background, border and header — the caller
        must re-render its value on top (e.g. by invalidating its
        last-rendered state before the next set_value).
        """
        if header_text == self.header_text:
            return
        self.header_text = header_text
        self._render_border_and_header()
        self._refresh_base_image()
        self.dirty = 1

    def _refresh_base_image(self):
        """Snapshot the painted chrome as the reset source for _render_value.

        Two blend-mode optimisations, both measured on a Pi 4 (1024x600,
        arm_freq=1000) and both producing pixel-identical output:

        1. ``_base_image`` is blitted over the whole of ``self.image`` on every
           value change. Both carry per-pixel alpha, so pygame does a full
           alpha composite — but the operation is semantically a *copy*
           ("reset image to base"). set_alpha(None) switches the source to a
           raw copy, alpha channel included, which is what the caller means.
           _render_value: 1282 -> 663 us.

        2. If the finished chrome is fully opaque, LayeredDirty's blit of this
           widget onto the screen is compositing a surface with nothing to
           composite. Disabling blending there makes it a raw copy too. Guarded
           by an actual alpha scan rather than assumed: a widget with genuinely
           transparent corners must keep blending, or it gets hard edges
           against the view background.
        """
        base = self.image.copy()
        base.set_alpha(None)
        self._base_image = base

        opaque = False
        try:
            from pygame import surfarray

            alpha = surfarray.pixels_alpha(self.image)
            opaque = bool(alpha.min() == 255)
            del alpha  # release the surface lock before blitting again
        except Exception:  # noqa: BLE001 - never fail a widget over an optimisation
            opaque = False
        # Glyphs blitted on top can only raise alpha, never lower it, so a
        # fully-opaque base stays fully opaque for the widget's lifetime.
        self.image.set_alpha(None if opaque else 255)

    def _get_digit_metrics(
        self,
        color: tuple[int, int, int],
        chars: str = ".:0123456789",
        punct_scale: float = 0.6,
    ):
        key = (id(self.font_value), bool(self.antialias), color, chars, punct_scale)
        cached = self._digit_cache.get(key)
        if cached is not None:
            return cached

        surf = {ch: self.font_value.render(ch, self.antialias, color) for ch in chars}
        h = max(s.get_height() for s in surf.values())
        advance = max(s.get_width() for s in surf.values())

        adv: dict[str, int] = {}
        for ch in chars:
            if ch in ".:":
                slot = int(max(surf[ch].get_width(), advance * punct_scale))
            else:
                slot = advance
            adv[ch] = slot

        packed = {"surf": surf, "h": h, "advance": advance, "adv": adv}
        self._digit_cache[key] = packed
        return packed

    def _fill_background(self, rect: pygame.Rect | None = None):
        """Fill the given rect with either gradient or flat bg_color.

        A whole-surface fill is clipped to the border radius. The background
        used to be filled square and the rounded border drawn over it, which
        left the fill showing in the four corners *outside* the border — a
        square shoulder on every rounded panel, invisible at radius 4 and
        obvious once a skin asks for a real radius. Sub-rect fills (the value
        area on a redraw) are interior and never touch a corner, so they skip
        the mask and stay cheap.
        """
        full = rect is None
        if rect is None:
            rect = self.image.get_rect()

        if self._bg_gradient_surface is not None:
            source = self._bg_gradient_surface.subsurface(rect).copy()
        else:
            source = pygame.Surface(rect.size, pygame.SRCALPHA)
            source.fill(self.bg_color)

        if full and self.border_radius > 0:
            mask = pygame.Surface(rect.size, pygame.SRCALPHA)
            pygame.draw.rect(
                mask,
                (255, 255, 255, 255),
                mask.get_rect(),
                border_radius=self.border_radius,
            )
            source = source.convert_alpha()
            source.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            # Clear first: the corners must end up transparent, and blitting
            # a masked surface over old pixels would leave them behind.
            self.image.fill((0, 0, 0, 0), rect)

        self.image.blit(source, rect)

    def _create_background_gradient(
        self,
        top_color: tuple[int, int, int] | None,
        bottom_color: tuple[int, int, int] | None,
    ) -> pygame.Surface | None:
        """Build the panel background ramp, or None for a flat fill.

        Subclasses override this to shape the ramp differently (the tyre
        cells use a radial glow); the two colours keep their meaning either
        way — `top_color` is the dark rim, `bottom_color` the lit end.
        """
        if top_color is None or bottom_color is None:
            return None
        return vertical_gradient((self.w, self.h), top_color, bottom_color)

    def _render_value(
        self,
        value_str: str,
        color: tuple[int, int, int] | None = None,
    ):
        if color is None:
            color = self.value_color or self.text_color

        metrics = self._get_digit_metrics(color)
        surf_map = metrics["surf"]
        digit_h = metrics["h"]
        advance_map = metrics["adv"]

        # area
        inner_left = self.border_width
        inner_right = self.w - self.border_width
        inner_top = self.border_width
        if self.header_text:
            inner_top = max(self._header_bottom + self.header_margin, inner_top)
        inner_bottom = self.h - self.border_width

        value_area = pygame.Rect(
            inner_left,
            inner_top,
            inner_right - inner_left,
            inner_bottom - inner_top,
        )

        self.image.blit(self._base_image, (0, 0))

        # total width from per-char advances
        advances = [advance_map.get(ch, metrics["advance"]) for ch in value_str]
        total_w = sum(advances) + max(0, len(value_str) - 1) * self.digit_gap

        x = value_area.centerx - total_w // 2
        y = value_area.centery - self.value_offset_y - digit_h // 2 - 2  # FIXME: -2

        for i, ch in enumerate(value_str):
            slot_w = advances[i]
            ch_surf = surf_map.get(ch)
            if ch_surf is None:
                ch_surf = self.font_value.render(ch, self.antialias, color)
            gx = x + (slot_w - ch_surf.get_width()) // 2
            gy = y + (digit_h - ch_surf.get_height()) // 2
            self.image.blit(ch_surf, (gx, gy))
            x += slot_w + self.digit_gap

        return value_area

    @abstractmethod
    def set_value(self, value: int):
        raise NotImplementedError

    @abstractmethod
    def update(self, bus: VehicleBus, dt: float):
        """
        Update the widget state.
        Must be implemented by subclasses.

        Args:
            bus (VehicleBus): The vehicle bus containing frame and signals.
            dt (float): Time delta since last frame.
        """
        raise NotImplementedError
