"""A live number with a unit, laid out so it cannot dance.

The dashboard gauges get this from ``Widget`` (see ``base/digits.py`` for
why it matters); this is the same treatment for a number that is *not* a
gauge — the acceleration timer's clock, which changes its hundredths 100
times a second and would otherwise squirm under the reader's eye.

Two rules on top of the fixed digit grid:

* the digits are right-aligned in a field sized from a ``template`` (the
  widest value the caller expects), so gaining a digit — 9.99 to 10.00 —
  shifts nothing that was already on screen;
* the unit sits at a fixed offset after that field, on the digits'
  *baseline* rather than their surface edge, so a smaller unit font still
  sits on the same line the digits stand on.

The whole block — field, gap, unit — is centred on the given position.
"""

from __future__ import annotations

import pygame
from pygame.sprite import DirtySprite

from .digits import digit_metrics


class DigitReadout(DirtySprite):
    def __init__(
        self,
        pos: tuple[int, int],
        font: pygame.font.Font,
        color: tuple[int, int, int],
        *,
        template: str = "00.00",
        unit: str = "",
        unit_font: pygame.font.Font | None = None,
        unit_color: tuple[int, int, int] | None = None,
        digit_gap: int = 0,
        unit_gap: int = 0,
        antialias: bool = True,
    ):
        super().__init__()
        self._pos = pos
        self._template = template
        self._digit_gap = int(digit_gap)
        self._unit_gap = int(unit_gap)

        self._metrics = digit_metrics(font, color, antialias=antialias)
        self._font = font

        self._unit_surf = None
        self._unit_top = 0
        if unit and unit_font is not None:
            self._unit_surf = unit_font.render(
                unit, antialias, unit_color if unit_color is not None else color
            )
            # Baseline alignment: both fonts' ascent is measured from the top
            # of the surface render() returns, so matching ascents puts the
            # two on one line whatever the size difference.
            self._unit_top = font.get_ascent() - unit_font.get_ascent()

        self._text = ""
        self._field_w = -1
        self.dirty = 1
        self.set_text("")

    @property
    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        text = str(text)
        if text == self._text and self._field_w >= 0:
            return
        self._text = text
        self._render()
        self.dirty = 1

    # ------------------------------------------------------------------
    def _render(self) -> None:
        metrics = self._metrics
        # The template fixes the width; a value that outgrows it (a run so
        # slow it passes 100 s) widens the block rather than losing its
        # leading digit.
        field_w = max(
            metrics.width(self._template, self._digit_gap),
            metrics.width(self._text, self._digit_gap),
        )

        unit_w = 0 if self._unit_surf is None else self._unit_surf.get_width()
        unit_gap = self._unit_gap if self._unit_surf is not None else 0
        width = field_w + unit_gap + unit_w
        height = metrics.height
        if self._unit_surf is not None:
            height = max(height, self._unit_top + self._unit_surf.get_height())

        # Transparent, so the view's dirty-rect clear() restores whatever is
        # behind it — this sprite makes no assumption about the background.
        self.image = pygame.Surface((width, height), pygame.SRCALPHA)
        if pygame.display.get_surface():
            self.image = self.image.convert_alpha()

        metrics.draw(
            self.image,
            self._text,
            self._digit_gap,
            field_w - metrics.width(self._text, self._digit_gap),
            0,
        )
        if self._unit_surf is not None:
            self.image.blit(self._unit_surf, (field_w + unit_gap, self._unit_top))

        self._field_w = field_w
        self.rect = self.image.get_rect(center=self._pos)
