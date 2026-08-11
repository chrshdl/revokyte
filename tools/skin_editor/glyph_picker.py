"""Modal glyph browser over the material-symbols face.

Enumerates the Private Use Area once (render-metrics filter drops .notdef
and blank cells), then shows a paginated grid; click a cell to apply the
glyph to the selected Icon. Drawn as an overlay with full event capture —
pygame has no OS dialogs.
"""

from __future__ import annotations

import pygame

from instrument_cluster.ui.utils import FontFamily, load_font_px

from . import uikit

_CACHE: list[str] | None = None

COLS, ROWS = 14, 9
CELL = 52


def _glyph_inventory() -> list[str]:
    global _CACHE
    if _CACHE is None:
        font = load_font_px(30, FontFamily.MATERIAL_SYMBOLS)
        out = []
        for cp in range(0xE000, 0xF8FF + 1):
            ch = chr(cp)
            metrics = font.metrics(ch)
            if not metrics or metrics[0] is None or metrics[0][4] == 0:
                continue
            surf = font.render(ch, True, (255, 255, 255))
            if surf.get_bounding_rect().width == 0:
                continue
            out.append(ch)
        _CACHE = out
    return _CACHE


class GlyphPicker:
    def __init__(self, rect, on_pick, on_close):
        self.rect = pygame.Rect(rect)
        self.on_pick = on_pick
        self.on_close = on_close
        self.page = 0
        self.glyphs = _glyph_inventory()
        self._hover: int | None = None
        self.font = load_font_px(30, FontFamily.MATERIAL_SYMBOLS)

        grid_w, grid_h = COLS * CELL, ROWS * CELL
        self.grid = pygame.Rect(0, 0, grid_w, grid_h)
        self.grid.center = self.rect.center

    @property
    def pages(self) -> int:
        per = COLS * ROWS
        return max(1, (len(self.glyphs) + per - 1) // per)

    def _cell_at(self, pos) -> int | None:
        if not self.grid.collidepoint(pos):
            return None
        col = (pos[0] - self.grid.x) // CELL
        row = (pos[1] - self.grid.y) // CELL
        idx = self.page * COLS * ROWS + row * COLS + col
        return idx if idx < len(self.glyphs) else None

    def handle(self, event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.on_close()
            elif event.key in (pygame.K_RIGHT, pygame.K_PAGEDOWN):
                self.page = min(self.pages - 1, self.page + 1)
            elif event.key in (pygame.K_LEFT, pygame.K_PAGEUP):
                self.page = max(0, self.page - 1)
            return True
        if event.type == pygame.MOUSEWHEEL:
            self.page = max(0, min(self.pages - 1, self.page - event.y))
            return True
        if event.type == pygame.MOUSEMOTION:
            self._hover = self._cell_at(event.pos)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            idx = self._cell_at(event.pos)
            if idx is not None:
                self.on_pick(self.glyphs[idx])
                self.on_close()
            elif not self.grid.inflate(40, 80).collidepoint(event.pos):
                self.on_close()
            return True
        return event.type not in (pygame.QUIT,)

    def draw(self, screen):
        scrim = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        scrim.fill((0, 0, 0, 170))
        screen.blit(scrim, self.rect.topleft)

        frame = self.grid.inflate(24, 64)
        pygame.draw.rect(screen, uikit.THEME["panel"], frame, border_radius=6)
        pygame.draw.rect(screen, uikit.THEME["panel_edge"], frame, 1, border_radius=6)
        uikit.text(
            screen,
            f"material symbols — page {self.page + 1}/{self.pages}   "
            "(wheel / arrows to page, Esc to close)",
            (frame.x + 12, frame.y + 8),
            uikit.THEME["text_dim"],
            uikit.small_font(),
        )

        start = self.page * COLS * ROWS
        for i in range(COLS * ROWS):
            idx = start + i
            if idx >= len(self.glyphs):
                break
            col, row = i % COLS, i // COLS
            cell = pygame.Rect(
                self.grid.x + col * CELL, self.grid.y + row * CELL, CELL, CELL
            )
            if idx == self._hover:
                pygame.draw.rect(screen, uikit.THEME["row_hover"], cell)
            surf = self.font.render(self.glyphs[idx], True, uikit.THEME["text"])
            screen.blit(surf, surf.get_rect(center=cell.center))
        if self._hover is not None and self._hover < len(self.glyphs):
            uikit.text(
                screen,
                "U+%04X" % ord(self.glyphs[self._hover]),
                (frame.right - 12, frame.y + 8),
                uikit.THEME["accent"],
                uikit.small_font(),
                right=True,
            )
