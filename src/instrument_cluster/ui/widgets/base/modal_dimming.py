"""Knock the live view back behind a modal.

Distinct from :class:`ModalBackdrop`, which is a patterned scrim specified in
raw alpha. This one says what it means — "dim by N percent" — because that is
the property a designer picks, and it is the only knob it has.

Black at alpha ``a`` composited over a pixel leaves ``original * (1 - a/255)``,
so a 35% dim is alpha 89. Expressing it as a percentage keeps that arithmetic
in one place instead of at every call site.

Note this sprite must be composited **at most once per frame** over the same
pixels: re-blitting a translucent fill over pixels it already dimmed darkens
them again, which makes slow-updating widgets underneath visibly pulse.
``OverlayWindow`` already guarantees that (see ui/window_layering.py).
"""

import pygame
from pygame.sprite import DirtySprite

from ...colors import Color


class ModalDimming(DirtySprite):
    """A full-area translucent black fill, specified as a dim percentage."""

    def __init__(self, size: tuple[int, int], *, percent: float = 35.0):
        super().__init__()
        self.rect = pygame.Rect(0, 0, *size)
        self.visible = 1
        self.dirty = 1
        self._percent = 0.0
        self.set_percent(percent)

    @property
    def percent(self) -> float:
        """How much the view beneath is knocked back, 0-100."""
        return self._percent

    @staticmethod
    def alpha_for(percent: float) -> int:
        """Alpha that dims by `percent` (0 = untouched, 100 = black)."""
        clamped = max(0.0, min(100.0, float(percent)))
        return round(255 * clamped / 100.0)

    def set_percent(self, percent: float) -> None:
        clamped = max(0.0, min(100.0, float(percent)))
        if clamped == self._percent and self.dirty == 0:
            return
        self._percent = clamped

        surf = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        surf.fill((*Color.BLACK.rgb(), self.alpha_for(clamped)))
        self.image = surf
        self.dirty = 1
