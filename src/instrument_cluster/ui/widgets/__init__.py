from abc import ABC, abstractmethod

import pygame
from pygame.sprite import DirtySprite

from ...core.vehicle.vehicle_bus import VehicleBus
from ..colors import Color
from ..utils import FontFamily, load_font


class Widget(DirtySprite, ABC):
    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str,
        anchor: str = "center",  # "topleft" or "center"
        header_margin: int = 8,  # brings `header_text` down by x pixels
        font_value_size: int = 32,
        font_value_family: FontFamily = FontFamily.D_DIN_EXP_BOLD,
        show_border: bool = True,
        antialias: bool = True,
        *,
        bg_color: tuple[int, int, int] = Color.BLACK.rgb(),
        text_color: tuple[int, int, int] = Color.WHITE.rgb(),
        # Custom-layout text color for the *value only* — the header
        # always renders in text_color (white). None keeps text_color.
        value_color: tuple[int, int, int] | None = None,
        border_color: tuple[int, int, int] | None = None,
        border_width: int = 2,
        border_radius: int = 4,
        bg_gradient_top: tuple[int, int, int] | None = None,
        bg_gradient_bottom: tuple[int, int, int] | None = None,
        font_scale: float = 1.0,
    ):
        super().__init__()
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
        # build widgets at arbitrary rects with font_scale = rect size /
        # design size, so a resized gauge reads proportionally — matching
        # the builder's stretched preview. 1.0 everywhere else.
        self.font_scale = float(font_scale)
        font_value_size = max(1, round(font_value_size * self.font_scale))
        header_size = max(1, round(32 * self.font_scale))
        self.font_header = load_font(size=header_size, family=FontFamily.PIXEL_TYPE)
        self.font_value = load_font(size=font_value_size, family=font_value_family)
        self.font_value_size = font_value_size
        self.header_text = header_text
        self.value_offset_y = 4
        self.bg_color = bg_color
        self.text_color = text_color
        self.value_color = value_color
        self.header_margin = header_margin
        self.antialias = antialias

        # create gradient surface or None
        self._bg_gradient_surface = self._create_vertical_gradient(
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
            self.border_color = Color.LIGHT_GREY.rgb()

        self.border_width = border_width
        self.border_radius = border_radius
        self.show_border = show_border

        self.image = pygame.Surface((self.w, self.h), pygame.SRCALPHA).convert_alpha()
        self.rect = self.image.get_rect(topleft=(tlx, tly))

        self._last_value_str = None
        self.digit_gap = -2

        # cache for digits keyed by
        # (font_id, antialias, color, chars, punct_scale)
        self._digit_cache: dict[tuple, dict] = {}

        self._render_border_and_header()
        self._base_image = self.image.copy()
        self.visible = 1
        self.dirty = 2

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

        header_surf = self.font_header.render(self.header_text, False, self.text_color)
        header_rect = header_surf.get_rect(midtop=(self.w // 2, self.header_margin))
        self.image.blit(header_surf, header_rect)
        self._header_bottom = header_rect.bottom

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
        self._base_image = self.image.copy()
        self.dirty = 1

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
        """Fill the given rect with either gradient or flat bg_color."""
        if rect is None:
            rect = self.image.get_rect()

        if self._bg_gradient_surface is not None:
            # draw the corresponding part of the gradient surface
            self.image.blit(self._bg_gradient_surface, rect, area=rect)
        else:
            pygame.draw.rect(self.image, self.bg_color, rect)

    def _create_vertical_gradient(
        self,
        top_color: tuple[int, int, int] | None,
        bottom_color: tuple[int, int, int] | None,
    ) -> pygame.Surface | None:
        if top_color is None or bottom_color is None:
            return None

        w, h = self.w, self.h
        surf = pygame.Surface((w, h))
        r1, g1, b1 = top_color
        r2, g2, b2 = bottom_color

        if h <= 1:
            surf.fill(top_color)
            return surf

        for y in range(h):
            # linear 0..1
            t_lin = y / (h - 1)

            # this makes the middle region flatter / brighter
            # try different exponents, e.g. 1.5, 2.0, 2.5
            t = t_lin**1.1

            r = int(r1 + (r2 - r1) * t)
            g = int(g1 + (g2 - g1) * t)
            b = int(b1 + (b2 - b1) * t)

            pygame.draw.line(surf, (r, g, b), (0, y), (w, y))

        return surf

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
        inner_top = max(self._header_bottom + self.header_margin, self.border_width)
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
