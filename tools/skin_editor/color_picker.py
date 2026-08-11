"""Modal palette picker: choose which global Color a widget role wears.

A grid of the palette's named swatches (live values, so palette overrides
show). Click applies, Esc closes. Same drawn-modal pattern as the glyph
picker — pygame has no OS dialogs.
"""

from __future__ import annotations

import pygame

from instrument_cluster.ui.colors import Color

from . import uikit

COLS = 4
CELL_W, CELL_H = 220, 40


class ColorPicker:
    def __init__(self, rect, current: str, on_pick, on_close):
        self.rect = pygame.Rect(rect)
        self.current = current
        self.on_pick = on_pick
        self.on_close = on_close
        self.colors = list(Color)
        self._hover: int | None = None

        rows = (len(self.colors) + COLS - 1) // COLS
        self.grid = pygame.Rect(0, 0, COLS * CELL_W, rows * CELL_H)
        self.grid.center = self.rect.center

    def _cell_at(self, pos) -> int | None:
        if not self.grid.collidepoint(pos):
            return None
        col = (pos[0] - self.grid.x) // CELL_W
        row = (pos[1] - self.grid.y) // CELL_H
        idx = row * COLS + col
        return idx if idx < len(self.colors) else None

    def handle(self, event) -> bool:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.on_close()
            return True
        if event.type == pygame.MOUSEMOTION:
            self._hover = self._cell_at(event.pos)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            idx = self._cell_at(event.pos)
            if idx is not None:
                self.on_pick(self.colors[idx].name)
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
            "palette — click a color, Esc to close",
            (frame.x + 12, frame.y + 8),
            uikit.THEME["text_dim"],
            uikit.small_font(),
        )

        for idx, color in enumerate(self.colors):
            col, row = idx % COLS, idx // COLS
            cell = pygame.Rect(
                self.grid.x + col * CELL_W, self.grid.y + row * CELL_H, CELL_W, CELL_H
            )
            if idx == self._hover:
                pygame.draw.rect(screen, uikit.THEME["row_hover"], cell)
            if color.name == self.current:
                pygame.draw.rect(screen, uikit.THEME["accent"], cell, 2)
            swatch = pygame.Rect(cell.x + 8, cell.y + 8, 44, CELL_H - 16)
            pygame.draw.rect(screen, color.rgb(), swatch)
            pygame.draw.rect(screen, uikit.THEME["panel_edge"], swatch, 1)
            uikit.text(
                screen,
                color.name,
                (swatch.right + 10, cell.y + 10),
                uikit.THEME["text"],
                uikit.font(14),
            )
