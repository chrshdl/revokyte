"""Fixed-slot digit layout — the reason gauge numbers don't dance.

In a proportional face a `1` is much narrower than an `8`, so a value that
changes every frame slides sideways under itself: a speed re-centred on each
reading is unreadable at a glance, and a running clock is worse, because its
hundredths change 100 times a second. Instrument clusters solve it the same
way mechanical odometers did — every character gets a slot as wide as the
widest digit and is centred in it, so a digit changes what it shows and never
where it sits. `.` and `:` take a narrower slot (``punct_scale``); at full
digit width they read as a gap.

This is the layout every dashboard gauge draws through (``Widget``), lifted
out of it so anything outside the dashboard that shows a live number gets the
identical treatment rather than a lookalike.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

# The characters worth pre-rendering: a gauge's value is digits, a decimal
# point and a lap-time colon. Anything else (a delta's sign, a unit) is
# rendered on the fly and still gets a slot.
DIGIT_CHARS = ".:0123456789"
PUNCT_SCALE = 0.6


@dataclass(frozen=True)
class DigitMetrics:
    """Pre-rendered glyphs and their slot widths for one font/colour pair.

    Building it renders every digit, so it is worth caching per widget —
    which is what the callers do.
    """

    font: pygame.font.Font
    color: tuple[int, int, int]
    antialias: bool
    surf: dict[str, pygame.Surface]
    height: int
    advance: int  # the widest digit: the standard slot
    adv: dict[str, int]  # per-character slot width

    def slot(self, ch: str) -> int:
        return self.adv.get(ch, self.advance)

    def width(self, text: str, gap: int) -> int:
        """Total width ``text`` will occupy, gaps included."""
        return sum(self.slot(ch) for ch in text) + max(0, len(text) - 1) * gap

    def draw(self, surface: pygame.Surface, text: str, gap: int, left: int, top: int):
        """Blit ``text`` on the grid, starting at (left, top). Returns the x
        the next character would start at."""
        x = left
        for ch in text:
            glyph = self.surf.get(ch)
            if glyph is None:
                glyph = self.font.render(ch, self.antialias, self.color)
            slot_w = self.slot(ch)
            surface.blit(
                glyph,
                (
                    x + (slot_w - glyph.get_width()) // 2,
                    top + (self.height - glyph.get_height()) // 2,
                ),
            )
            x += slot_w + gap
        return x


def digit_metrics(
    font: pygame.font.Font,
    color: tuple[int, int, int],
    antialias: bool = True,
    chars: str = DIGIT_CHARS,
    punct_scale: float = PUNCT_SCALE,
) -> DigitMetrics:
    surf = {ch: font.render(ch, antialias, color) for ch in chars}
    height = max(s.get_height() for s in surf.values())
    advance = max(s.get_width() for s in surf.values())

    adv: dict[str, int] = {}
    for ch in chars:
        if ch in ".:":
            adv[ch] = int(max(surf[ch].get_width(), advance * punct_scale))
        else:
            adv[ch] = advance

    return DigitMetrics(
        font=font,
        color=color,
        antialias=antialias,
        surf=surf,
        height=height,
        advance=advance,
        adv=adv,
    )
