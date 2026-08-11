"""The WYSIWYG canvas: the rendered view, scaled to fit, with direct
manipulation of bound skin fields (select, drag, resize, nudge).

Drag semantics per binding kind:

* RECT — body drag moves x/y; the 8 handles resize. Center-anchored rects
  keep their stored (cx, cy, w, h) form: moving edits the center, resizing
  an edge grows the box symmetrically about it (matching how the widget
  will actually re-anchor).
* POINT — body drag moves the stored (x, y).
* HLINE / VLINE — drag edits the single stored coordinate.

A gesture is one undo entry: the old value is captured on mouse-down and
pushed on mouse-up (drag coalescing).
"""

from __future__ import annotations

import pygame

from . import uikit
from .bindings import HLINE, POINT, RECT, VLINE, Binding

HANDLE = 7  # px, screen-space handle half-size


class Canvas:
    def __init__(self, rect, *, on_edit, on_select, on_gesture_end):
        self.rect = pygame.Rect(rect)
        self.on_edit = on_edit  # (path, value) -> None (live, no undo push)
        self.on_select = on_select  # (Binding | None) -> None
        self.on_gesture_end = on_gesture_end  # (path, old_value) -> None
        self.bindings: list[Binding] = []
        self.selected: Binding | None = None
        self.surface: pygame.Surface | None = None
        self.scale = 1.0
        self.origin = (0, 0)  # top-left of the scaled view inside self.rect
        self.zoom_full = False  # False = fit, True = 100%

        self._drag = None  # dict(mode, binding, start_mouse, start_value, old)

    # ------------------------------------------------------------------
    # geometry
    # ------------------------------------------------------------------
    def set_surface(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self._layout()

    def _layout(self) -> None:
        if self.surface is None:
            return
        vw, vh = self.surface.get_size()
        if self.zoom_full:
            self.scale = 1.0
        else:
            self.scale = min(
                (self.rect.width - 24) / vw, (self.rect.height - 24) / vh, 1.0
            )
        sw, sh = int(vw * self.scale), int(vh * self.scale)
        self.origin = (
            self.rect.x + (self.rect.width - sw) // 2,
            self.rect.y + (self.rect.height - sh) // 2,
        )

    def to_view(self, pos) -> tuple[float, float]:
        return (
            (pos[0] - self.origin[0]) / self.scale,
            (pos[1] - self.origin[1]) / self.scale,
        )

    def to_screen_rect(self, r: pygame.Rect) -> pygame.Rect:
        return pygame.Rect(
            round(self.origin[0] + r.x * self.scale),
            round(self.origin[1] + r.y * self.scale),
            max(1, round(r.width * self.scale)),
            max(1, round(r.height * self.scale)),
        )

    # ------------------------------------------------------------------
    # selection + handles
    # ------------------------------------------------------------------
    def _handles(self, srect: pygame.Rect):
        cx, cy = srect.centerx, srect.centery
        return {
            "nw": (srect.left, srect.top), "n": (cx, srect.top), "ne": (srect.right, srect.top),
            "w": (srect.left, cy), "e": (srect.right, cy),
            "sw": (srect.left, srect.bottom), "s": (cx, srect.bottom), "se": (srect.right, srect.bottom),
        }

    def _hit_handle(self, pos, srect) -> str | None:
        for name, (hx, hy) in self._handles(srect).items():
            if abs(pos[0] - hx) <= HANDLE and abs(pos[1] - hy) <= HANDLE:
                return name
        return None

    def _hit_binding(self, skin, pos) -> Binding | None:
        vx, vy = self.to_view(pos)
        best, best_area = None, None
        for b in self.bindings:
            r = b.rect_fn(skin)
            if r.collidepoint(vx, vy):
                area = r.width * r.height
                if best is None or area < best_area:
                    best, best_area = b, area
        return best

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    def handle(self, event, skin, get_value) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self.rect.collidepoint(event.pos):
                return False
            # Handle grab on the current selection first.
            if self.selected is not None and self.selected.kind == RECT:
                srect = self.to_screen_rect(self.selected.rect_fn(skin))
                handle = self._hit_handle(event.pos, srect)
                if handle:
                    self._begin(event.pos, self.selected, "resize:" + handle, get_value)
                    return True
            hit = self._hit_binding(skin, event.pos)
            self.selected = hit
            self.on_select(hit)
            if hit is not None:
                self._begin(event.pos, hit, "move", get_value)
            return True

        if self._drag and event.type == pygame.MOUSEMOTION:
            self._drag_to(event.pos)
            return True

        if self._drag and event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            drag = self._drag
            self._drag = None
            if drag["moved"]:
                self.on_gesture_end(drag["binding"].path, drag["old"])
            return True
        return False

    def nudge(self, skin, dx: int, dy: int, get_value) -> bool:
        """Arrow-key nudge of the selected binding (one undo entry each)."""
        b = self.selected
        if b is None:
            return False
        value = get_value(b.path)
        old = value
        if b.kind == RECT:
            x, y, w, h = value
            value = (x + dx, y + dy, w, h)
        elif b.kind == POINT:
            value = (value[0] + dx, value[1] + dy)
        elif b.kind == HLINE:
            if dy == 0:
                return False
            value = value + dy
        elif b.kind == VLINE:
            if dx == 0:
                return False
            value = value + dx
        self.on_edit(b.path, value)
        self.on_gesture_end(b.path, old)
        return True

    def _begin(self, pos, binding, mode, get_value):
        self._drag = {
            "mode": mode,
            "binding": binding,
            "start": pos,
            "value": get_value(binding.path),
            "old": get_value(binding.path),
            "moved": False,
        }

    def _drag_to(self, pos):
        drag = self._drag
        b = drag["binding"]
        dx = (pos[0] - drag["start"][0]) / self.scale
        dy = (pos[1] - drag["start"][1]) / self.scale
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            return
        drag["moved"] = True
        value = drag["value"]
        mode = drag["mode"]

        if b.kind == POINT:
            new = (round(value[0] + dx), round(value[1] + dy))
        elif b.kind == HLINE:
            new = round(value + dy)
        elif b.kind == VLINE:
            new = round(value + dx)
        elif b.kind == RECT and mode == "move":
            x, y, w, h = value
            new = (round(x + dx), round(y + dy), w, h)
        elif b.kind == RECT:  # resize:<handle>
            new = self._resize(value, mode.split(":", 1)[1], dx, dy, b.anchor)
        else:
            return
        self.on_edit(b.path, new)

    @staticmethod
    def _resize(value, handle, dx, dy, anchor):
        x, y, w, h = value
        if anchor == "center":
            # Stored (cx, cy, w, h): dragging an edge grows the box
            # symmetrically about the center, which is how the widget will
            # re-anchor when rebuilt.
            if "e" in handle:
                w = w + 2 * dx
            if "w" in handle:
                w = w - 2 * dx
            if "s" in handle:
                h = h + 2 * dy
            if "n" in handle:
                h = h - 2 * dy
            return (x, y, round(max(1, w)), round(max(1, h)))
        # topleft-stored rect: opposite edge stays anchored.
        if "e" in handle:
            w = w + dx
        if "w" in handle:
            x, w = x + dx, w - dx
        if "s" in handle:
            h = h + dy
        if "n" in handle:
            y, h = y + dy, h - dy
        return (round(x), round(y), round(max(1, w)), round(max(1, h)))

    # ------------------------------------------------------------------
    # drawing
    # ------------------------------------------------------------------
    def draw(self, screen, skin, error: str | None = None):
        pygame.draw.rect(screen, uikit.THEME["canvas_bg"], self.rect)
        self._checkerboard(screen)
        if self.surface is None:
            return
        self._layout()
        sw = int(self.surface.get_width() * self.scale)
        sh = int(self.surface.get_height() * self.scale)
        scaled = (
            self.surface
            if self.scale == 1.0
            else pygame.transform.smoothscale(self.surface, (sw, sh))
        )
        screen.blit(scaled, self.origin)
        frame = pygame.Rect(self.origin, (sw, sh)).inflate(2, 2)
        pygame.draw.rect(screen, uikit.THEME["panel_edge"], frame, 1)

        if error:
            uikit.text(
                screen,
                f"view failed to render: {error}",
                (self.rect.x + 16, self.rect.y + 8),
                uikit.THEME["danger"],
            )

        if self.selected is not None:
            srect = self.to_screen_rect(self.selected.rect_fn(skin))
            color = uikit.THEME["outline"]
            if self.selected.kind in (HLINE,):
                pygame.draw.line(
                    screen, color, (srect.left, srect.centery), (srect.right, srect.centery), 2
                )
            elif self.selected.kind in (VLINE,):
                pygame.draw.line(
                    screen, color, (srect.centerx, srect.top), (srect.centerx, srect.bottom), 2
                )
            else:
                pygame.draw.rect(screen, color, srect, 2)
            if self.selected.kind == RECT:
                for hx, hy in self._handles(srect).values():
                    pygame.draw.rect(
                        screen,
                        uikit.THEME["handle"],
                        (hx - 4, hy - 4, 8, 8),
                    )
                    pygame.draw.rect(
                        screen, color, (hx - 4, hy - 4, 8, 8), 1
                    )
            elif self.selected.kind == POINT:
                pygame.draw.line(
                    screen, color, (srect.centerx - 10, srect.centery), (srect.centerx + 10, srect.centery), 1
                )
                pygame.draw.line(
                    screen, color, (srect.centerx, srect.centery - 10), (srect.centerx, srect.centery + 10), 1
                )

    def _checkerboard(self, screen):
        tile = 16
        a, b = uikit.THEME["checker_a"], uikit.THEME["checker_b"]
        prev_clip = screen.get_clip()
        screen.set_clip(self.rect)
        for yy in range(self.rect.y, self.rect.bottom, tile):
            for xx in range(self.rect.x, self.rect.right, tile):
                color = a if ((xx // tile) + (yy // tile)) % 2 == 0 else b
                pygame.draw.rect(screen, color, (xx, yy, tile, tile))
        screen.set_clip(prev_clip)
