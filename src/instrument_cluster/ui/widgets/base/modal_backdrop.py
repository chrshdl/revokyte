import pygame
from pygame.sprite import DirtySprite

from ...colors import Color


class ModalBackdrop(DirtySprite):
    def __init__(
        self,
        size: tuple[int, int],
        *,
        alpha: int = 128,
        pattern: pygame.Surface | None = None,
    ):
        super().__init__()
        self.rect = pygame.Rect(0, 0, *size)
        self.visible = False
        self.dirty = 1

        self._alpha = int(alpha)
        self._pattern = pattern.convert_alpha() if pattern is not None else None

        self._rebuild()

    def _rebuild(self) -> None:
        w, h = self.rect.size
        surf = pygame.Surface((w, h), pygame.SRCALPHA)

        # Dim strength: translucent black at self._alpha (0 = live view
        # untouched, 255 = fully black). With a pattern, its opaque dots
        # tile over the fill and alpha darkens the gaps between them.
        surf.fill((*Color.BLACK.rgb(), self._alpha))

        if self._pattern is not None:
            pw, ph = self._pattern.get_size()
            for y in range(0, h, ph):
                for x in range(0, w, pw):
                    surf.blit(self._pattern, (x, y))

        self.image = surf
        self.dirty = 1

    def set_pattern(self, pattern: pygame.Surface | None) -> None:
        self._pattern = pattern.convert_alpha() if pattern is not None else None
        self._rebuild()
        self.dirty = 1

    def set_alpha(self, alpha: int) -> None:
        self._alpha = int(alpha)
        self._rebuild()
        self.dirty = 1

    def show(self):
        if not self.visible:
            self.visible = True
            self._rebuild()
            self.dirty = 1

    def hide(self):
        if self.visible:
            self.visible = False
            # Replace image with fully transparent surface
            w, h = self.rect.size
            self.image = pygame.Surface((w, h), pygame.SRCALPHA)
            self.dirty = 1
