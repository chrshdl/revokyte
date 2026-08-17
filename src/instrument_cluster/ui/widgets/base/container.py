from __future__ import annotations

from collections.abc import Iterable

import pygame
from pygame.sprite import LayeredDirty, Sprite


class Container:
    """Container with a position; children keep local rects relative to it.

    - Set container.pos -> all children's rects update.
    - Move container -> all children move accordingly.
    - For children with `rect`, we remember their  local rect at add()-time.
    - For children that are Containers, we simply treat their .pos as local too.
    """

    def __init__(self, x: int = 0, y: int = 0, is_visible: bool = True):
        self.is_visible = is_visible
        self.pos = pygame.Vector2(x, y)
        self._children: list[object] = []
        self._locals: dict[object, pygame.Rect] = {}

    def add(self, *widgets: Iterable[object]) -> None:
        for w in widgets:
            self._children.append(w)

            if hasattr(w, "rect"):
                self._locals[w] = pygame.Rect(w.rect)
                self._apply_world_rect(w)
            elif isinstance(w, Container):
                # container-within-container; treat its .pos as local,
                w.set_pos(int(self.pos.x + w.pos.x), int(self.pos.y + w.pos.y))

    def remove(self, *widgets: Iterable[object]) -> None:
        for w in widgets:
            if w in self._children:
                self._children.remove(w)
            self._locals.pop(w, None)

    def clear(self) -> None:
        self._children.clear()
        self._locals.clear()

    def set_pos(self, x: int, y: int) -> None:
        """Place container at absolute position, updating children."""
        dx, dy = x - self.pos.x, y - self.pos.y
        self.pos.update(x, y)
        # shift all rects by (dx, dy)
        for w in self._children:
            if hasattr(w, "rect"):
                w.rect.move_ip(dx, dy)
            elif isinstance(w, Container):
                w.set_pos(int(w.pos.x + dx), int(w.pos.y + dy))

    def move_ip(self, dx: int, dy: int) -> None:
        """Move in-place; children follow."""
        self.set_pos(int(self.pos.x + dx), int(self.pos.y + dy))

    def set_child_local(self, w: object, x: int, y: int) -> None:
        """Change a child's local topleft (relative to this container)."""
        if w not in self._children:
            return
        if hasattr(w, "rect"):
            local = self._locals.setdefault(w, pygame.Rect(w.rect))
            local.topleft = (x, y)
            self._apply_world_rect(w)
        elif isinstance(w, Container):
            w.set_pos(int(self.pos.x + x), int(self.pos.y + y))

    def _apply_world_rect(self, w: object) -> None:
        """Place child's *world* rect from stored local + our pos."""
        if hasattr(w, "rect"):
            local = self._locals.get(w)
            if local is None:
                return
            w.rect.topleft = (
                int(self.pos.x + local.x),
                int(self.pos.y + local.y),
            )

    def draw(self, surface: pygame.Surface) -> None:
        if not self.is_visible:
            return
        for w in self._children:
            if hasattr(w, "draw"):
                w.draw(surface)

    def handle_event(self, event) -> None:
        if not self.is_visible:
            return
        for w in self._children:
            if hasattr(w, "handle_event"):
                w.handle_event(event)

    def update(self, dt: float) -> None:
        for w in self._children:
            if hasattr(w, "update"):
                w.update(dt)

    def _iter_sprites(self):
        for w in self._children:
            if isinstance(w, Sprite):
                yield w
            elif isinstance(w, Container):
                yield from w._iter_sprites()

    def sprites(self):
        return list(self._iter_sprites())

    def add_to_layered(self, layered: LayeredDirty):
        layered.add(*self.sprites())
