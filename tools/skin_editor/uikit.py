"""The editor's own minimal widget kit.

Deliberately independent of the cluster's skin/widget stack: editing the
800x480 skin must never restyle the editor chrome, so everything here uses
a fixed theme and fixed font sizes. Retained-mode-lite: each control has a
rect, ``draw(surface)`` and ``handle(event) -> bool`` (True = consumed).
Mouse coordinates are window coordinates (the editor window is never
SCALED, so no mapping is needed).
"""

from __future__ import annotations

from collections.abc import Callable

import pygame

from instrument_cluster.ui.utils import FontFamily, load_font_px

THEME = {
    "bg": (24, 26, 30),
    "panel": (32, 35, 41),
    "panel_edge": (52, 56, 64),
    "row": (32, 35, 41),
    "row_hover": (44, 48, 56),
    "row_selected": (24, 64, 110),
    "text": (222, 224, 228),
    "text_dim": (140, 145, 152),
    "accent": (86, 156, 255),
    "accent_down": (60, 110, 190),
    "danger": (240, 90, 80),
    "dirty": (255, 190, 80),
    "canvas_bg": (16, 17, 19),
    "checker_a": (28, 30, 34),
    "checker_b": (22, 24, 27),
    "outline": (86, 156, 255),
    "handle": (255, 255, 255),
}


def font(size: int = 15) -> pygame.font.Font:
    return load_font_px(size, FontFamily.NOTOSANS_REGULAR)


def small_font() -> pygame.font.Font:
    return font(13)


def icon_font(size: int = 18) -> pygame.font.Font:
    return load_font_px(size, FontFamily.MATERIAL_SYMBOLS)


# Editor-chrome glyphs (material symbols). Deliberately NOT in the HMI's
# ui/icons.py registry: that file is the *cluster's* iconography and is
# designer-editable; the editor's own chrome must stay stable while it is
# being used to restyle the app.
ICON_SAVE = "\ue161"
ICON_UNDO = "\ue166"
ICON_REDO = "\ue15a"


def text(surface, s, pos, color=None, fnt=None, right=False, center=False):
    surf = (fnt or font()).render(str(s), True, color or THEME["text"])
    rect = surf.get_rect()
    if center:
        rect.center = pos
    elif right:
        rect.topright = pos
    else:
        rect.topleft = pos
    surface.blit(surf, rect)
    return rect


def panel(surface, rect, title=None):
    pygame.draw.rect(surface, THEME["panel"], rect)
    pygame.draw.rect(surface, THEME["panel_edge"], rect, 1)
    if title:
        text(surface, title, (rect.x + 10, rect.y + 6), THEME["text_dim"], small_font())


class Button:
    def __init__(
        self,
        rect,
        label,
        on_click: Callable,
        *,
        toggle_state=None,
        enabled: Callable[[], bool] | None = None,
        accent: bool = False,
        icon: str | None = None,
    ):
        self.rect = pygame.Rect(rect)
        self.label = label  # str or Callable[[], str]
        self.on_click = on_click
        self.toggle_state = toggle_state  # optional Callable[[], bool]
        self.enabled = enabled or (lambda: True)
        #: accent buttons (Save) light up in the accent color when enabled,
        #: so an actionable button never reads as inert chrome.
        self.accent = accent
        #: optional material-symbols glyph drawn left of the label.
        self.icon = icon
        self._hover = False

    def label_text(self) -> str:
        return self.label() if callable(self.label) else self.label

    def handle(self, event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self._hover = self.rect.collidepoint(event.pos)
            return False
        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.rect.collidepoint(event.pos)
        ):
            if self.enabled():
                self.on_click()
            return True
        return False

    def draw(self, surface):
        active = self.toggle_state() if self.toggle_state else False
        if not self.enabled():
            bg, fg = THEME["panel"], THEME["text_dim"]
        elif self.accent:
            bg = THEME["accent_down"] if not self._hover else THEME["accent"]
            fg = (255, 255, 255)
        elif active:
            bg, fg = THEME["row_selected"], THEME["text"]
        elif self._hover:
            bg, fg = THEME["row_hover"], THEME["text"]
        else:
            bg, fg = THEME["row"], THEME["text"]
        pygame.draw.rect(surface, bg, self.rect, border_radius=4)
        pygame.draw.rect(surface, THEME["panel_edge"], self.rect, 1, border_radius=4)
        label_surf = font().render(self.label_text(), True, fg)
        if self.icon:
            icon_surf = icon_font().render(self.icon, True, fg)
            gap = 6
            total = icon_surf.get_width() + gap + label_surf.get_width()
            x = self.rect.centerx - total // 2
            surface.blit(
                icon_surf,
                icon_surf.get_rect(midleft=(x, self.rect.centery)),
            )
            surface.blit(
                label_surf,
                label_surf.get_rect(
                    midleft=(x + icon_surf.get_width() + gap, self.rect.centery)
                ),
            )
        else:
            surface.blit(label_surf, label_surf.get_rect(center=self.rect.center))


class Stepper:
    """`- [value] +` numeric control with click-and-hold repeat.

    Double-clicking the value cell opens inline text entry: type a number,
    Enter commits (through the same ``apply`` callback, as an absolute
    set), Esc discards. Only int-valued steppers offer entry — the family
    cycler's value is a name, not a number.
    """

    REPEAT_DELAY = 0.35
    REPEAT_RATE = 0.045
    DOUBLE_CLICK_MS = 400

    def __init__(self, rect, label, get, apply, step=1):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.get = get
        self.apply = apply  # apply(delta) — delta is added to the value
        self.step = step
        self._held = 0  # -1 / +1 while a button is held
        self._held_t = 0.0
        self._repeating = False
        self._editing = False
        self._buffer = ""
        self._select_all = False
        self._last_mid_click = -10_000

    def _zones(self):
        h = self.rect.height
        minus = pygame.Rect(self.rect.x, self.rect.y, h, h)
        plus = pygame.Rect(self.rect.right - h, self.rect.y, h, h)
        mid = pygame.Rect(minus.right, self.rect.y, plus.x - minus.right, h)
        return minus, mid, plus

    # -- inline entry ----------------------------------------------------
    @property
    def editing(self) -> bool:
        return self._editing

    def _begin_edit(self) -> bool:
        value = self.get()
        if not isinstance(value, int):
            return False
        self._editing = True
        self._buffer = str(value)
        # The current value starts selected: the first keystroke replaces
        # it (double-click-to-retype, the behavior every entry field has).
        self._select_all = True
        return True

    def _cancel_edit(self) -> None:
        self._editing = False
        self._buffer = ""
        self._select_all = False

    def _commit_edit(self) -> None:
        buffer = self._buffer
        self._cancel_edit()
        try:
            target = int(buffer)
        except ValueError:
            return  # empty or lone "-": treat like Esc
        current = self.get()
        if target != current:
            self.apply(target - current)

    def handle_key(self, event) -> bool:
        """Feed a KEYDOWN while editing. Returns True when consumed —
        every key is, so shortcuts can't fire mid-entry."""
        if not self._editing or event.type != pygame.KEYDOWN:
            return False
        if event.key == pygame.K_ESCAPE:
            self._cancel_edit()
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._commit_edit()
        elif event.key == pygame.K_BACKSPACE:
            self._buffer = "" if self._select_all else self._buffer[:-1]
            self._select_all = False
        elif event.unicode.isdigit():
            if self._select_all:
                self._buffer = ""
                self._select_all = False
            self._buffer += event.unicode
        elif event.unicode == "-":
            if self._select_all:
                self._buffer = ""
                self._select_all = False
            if not self._buffer:
                self._buffer = "-"
        return True

    # -- mouse -----------------------------------------------------------
    def handle(self, event) -> bool:
        minus, mid, plus = self._zones()
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._editing:
                if mid.collidepoint(event.pos):
                    return True
                # Clicking anywhere else discards the entry; the click then
                # proceeds to whatever it landed on.
                self._cancel_edit()
                return False
            if minus.collidepoint(event.pos):
                self.apply(-self.step)
                self._held, self._held_t, self._repeating = -1, 0.0, False
                return True
            if plus.collidepoint(event.pos):
                self.apply(+self.step)
                self._held, self._held_t, self._repeating = +1, 0.0, False
                return True
            if mid.collidepoint(event.pos):
                now = pygame.time.get_ticks()
                if now - self._last_mid_click <= self.DOUBLE_CLICK_MS:
                    self._begin_edit()
                self._last_mid_click = now
                return True
        if event.type == pygame.MOUSEBUTTONUP and self._held:
            self._held = 0
            return False
        if (
            not self._editing
            and event.type == pygame.MOUSEWHEEL
            and self.rect.collidepoint(pygame.mouse.get_pos())
        ):
            self.apply(self.step * (1 if event.y > 0 else -1))
            return True
        return False

    def update(self, dt: float) -> None:
        if not self._held:
            return
        self._held_t += dt
        threshold = self.REPEAT_RATE if self._repeating else self.REPEAT_DELAY
        if self._held_t >= threshold:
            self._held_t = 0.0
            self._repeating = True
            self.apply(self._held * self.step)

    def draw(self, surface):
        minus, mid, plus = self._zones()
        for zone, glyph in ((minus, "-"), (plus, "+")):
            pygame.draw.rect(surface, THEME["row"], zone, border_radius=4)
            pygame.draw.rect(surface, THEME["panel_edge"], zone, 1, border_radius=4)
            text(surface, glyph, zone.center, THEME["accent"], center=True)
        pygame.draw.rect(surface, THEME["panel"], mid)
        if self._editing:
            pygame.draw.rect(surface, THEME["accent"], mid, 2)
            if self._select_all and self._buffer:
                # Selected text: highlight bar behind the value.
                sel = font().render(self._buffer, True, (255, 255, 255))
                bar = sel.get_rect(center=mid.center).inflate(8, 2)
                pygame.draw.rect(surface, THEME["accent_down"], bar)
                surface.blit(sel, sel.get_rect(center=mid.center))
            else:
                caret = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else " "
                text(surface, self._buffer + caret, mid.center, center=True)
        else:
            pygame.draw.rect(surface, THEME["panel_edge"], mid, 1)
            text(surface, self.get(), mid.center, center=True)
        if self.label:
            text(
                surface,
                self.label,
                (self.rect.x, self.rect.y - 16),
                THEME["text_dim"],
                small_font(),
            )


class ScrollList:
    """Scrollable list of rows. Rows are (key, label, depth, kind) tuples;
    ``kind`` picks the style ("group" headers vs "leaf" fields)."""

    ROW_H = 24

    def __init__(self, rect, on_select: Callable[[object], None]):
        self.rect = pygame.Rect(rect)
        self.rows: list[tuple] = []
        self.on_select = on_select
        self.selected_key = None
        self.offset = 0
        self._hover_index = None

    def set_rows(self, rows) -> None:
        self.rows = list(rows)
        self.offset = min(self.offset, self.max_offset)

    @property
    def max_offset(self) -> int:
        return max(0, len(self.rows) * self.ROW_H - self.rect.height)

    def scroll_to_key(self, key) -> None:
        for i, row in enumerate(self.rows):
            if row[0] == key:
                y = i * self.ROW_H
                if y < self.offset or y > self.offset + self.rect.height - self.ROW_H:
                    self.offset = max(
                        0, min(self.max_offset, y - self.rect.height // 2)
                    )
                return

    def _index_at(self, pos):
        if not self.rect.collidepoint(pos):
            return None
        i = (pos[1] - self.rect.y + self.offset) // self.ROW_H
        return int(i) if 0 <= i < len(self.rows) else None

    def handle(self, event) -> bool:
        if event.type == pygame.MOUSEWHEEL and self.rect.collidepoint(
            pygame.mouse.get_pos()
        ):
            self.offset = max(0, min(self.max_offset, self.offset - event.y * 48))
            return True
        if event.type == pygame.MOUSEMOTION:
            self._hover_index = self._index_at(event.pos)
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            i = self._index_at(event.pos)
            if i is not None:
                key, _label, _depth, kind = self.rows[i]
                if kind == "leaf":
                    self.selected_key = key
                    self.on_select(key)
                return True
        return False

    def draw(self, surface):
        prev_clip = surface.get_clip()
        surface.set_clip(self.rect)
        pygame.draw.rect(surface, THEME["panel"], self.rect)
        first = self.offset // self.ROW_H
        last = min(len(self.rows), first + self.rect.height // self.ROW_H + 2)
        for i in range(first, last):
            key, label, depth, kind = self.rows[i]
            y = self.rect.y + i * self.ROW_H - self.offset
            row_rect = pygame.Rect(self.rect.x, y, self.rect.width, self.ROW_H)
            if kind == "leaf" and key == self.selected_key:
                pygame.draw.rect(surface, THEME["row_selected"], row_rect)
            elif i == self._hover_index and kind == "leaf":
                pygame.draw.rect(surface, THEME["row_hover"], row_rect)
            color = THEME["text_dim"] if kind == "group" else THEME["text"]
            fnt = small_font() if kind == "group" else font(14)
            text(surface, label, (row_rect.x + 10 + depth * 14, y + 3), color, fnt)
        surface.set_clip(prev_clip)
        pygame.draw.rect(surface, THEME["panel_edge"], self.rect, 1)
        if self.max_offset:
            frac = self.rect.height / (len(self.rows) * self.ROW_H)
            thumb_h = max(24, int(self.rect.height * frac))
            thumb_y = self.rect.y + int(
                (self.rect.height - thumb_h) * (self.offset / self.max_offset)
            )
            pygame.draw.rect(
                surface,
                THEME["panel_edge"],
                (self.rect.right - 6, thumb_y, 4, thumb_h),
                border_radius=2,
            )
