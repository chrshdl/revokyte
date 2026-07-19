import pygame
from pygame.sprite import DirtySprite

from ...colors import Color


class Label(DirtySprite):
    def __init__(
        self,
        text,
        font: pygame.font.Font = None,
        color: tuple[int, int, int] = Color.WHITE.rgb(),
        pos: tuple[int, int] = (0, 0),
        center: bool = True,
        antialias: bool = True,
        *,
        visible=True,
        bg_color: tuple[int, int, int] | None = None,
    ):
        super().__init__()
        self._text = None
        self.font = font
        self.color = color
        self.pos = pos
        self.center = center
        self.antialias = antialias

        self.bg_color = bg_color

        self.visible = visible  # sprite will be drawn
        self.dirty = 1  # ensures initial draw
        self.set_text(text)

    @property
    def text(self):
        return self._text

    def set_visible(self, is_visible: bool) -> None:
        """
        Toggle visibility and mark dirty to ensure screen updates.
        """
        if self.visible != is_visible:
            self.visible = is_visible
            self.dirty = 1

    def set_bg_color(self, bg_color: tuple[int, int, int] | None) -> None:
        if bg_color != self.bg_color:
            self.bg_color = bg_color
            # re-render without changing text
            self._rerender()

    def set_text(self, text: str):
        # Convert to string to avoid errors if non-string passed
        text = str(text) if text is not None else ""
        if text != self._text:
            self._text = text
            self._rerender()

    def _rerender(self) -> None:
        # Render text
        text_surf = self.font.render(self._text, self.antialias, self.color)

        # If no background, behave exactly like before
        if self.bg_color is None:
            self.image = (
                text_surf.convert_alpha() if pygame.display.get_surface() else text_surf
            )
        else:
            w, h = text_surf.get_size()
            surf = pygame.Surface((w, h), pygame.SRCALPHA)
            surf.fill((*self.bg_color, 255))
            surf.blit(text_surf, (0, 0))
            self.image = surf.convert_alpha() if pygame.display.get_surface() else surf

        # Keep anchor (center or topleft) stable when size changes
        if hasattr(self, "rect"):
            anchor = self.rect.center if self.center else self.rect.topleft
        else:
            anchor = self.pos

        if self.center:
            self.rect = self.image.get_rect(center=anchor)
        else:
            self.rect = self.image.get_rect(topleft=anchor)

        self.dirty = 1
