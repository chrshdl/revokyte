import pygame

from ...colors import Color
from .label import Label


class TextField(Label):
    def __init__(
        self,
        text,
        font,
        color,
        pos,
        width,
        height,
        *,
        antialias=True,
        border_color=None,
        background_color=None,
        blinking_cursor=True,
        mask=False,
    ):
        # --- state used by set_text / draw / update ---
        self.cursor_position = 0
        self.cursor_visible = True
        self.cursor_timer = 0.0
        self.blinking_cursor = blinking_cursor
        self.antialias = antialias
        self.border_color = (
            Color.LIGHT_GREY.rgb() if border_color is None else border_color
        )
        self.background_color = (
            Color.GREY.rgb() if background_color is None else background_color
        )
        self.active = False

        # Password-style masking: when enabled the field renders bullets in
        # place of the real characters; the real text still lives in self.text.
        self.mask = mask
        self._reveal = False

        # --- IMPORTANT: define fixed box geometry BEFORE super().__init__ ---
        self._box_size = (width, height)
        self.rect = pygame.Rect(pos[0], pos[1], width, height)
        self.image = pygame.Surface(self._box_size, pygame.SRCALPHA)

        # Parent init (may call set_text, which now safely sees _box_size)
        super().__init__(text, font, color, pos, center=False, antialias=antialias)

        # caret at end of initial text
        self.cursor_position = len(self.text)

        # Initial compose
        self._rebuild_image()

    def _display_text(self) -> str:
        """Return the string actually drawn (masked unless revealed)."""
        if self.mask and not self._reveal:
            return "•" * len(self.text)
        return self.text

    def set_reveal(self, reveal: bool) -> None:
        """Show/hide the real characters of a masked field."""
        reveal = bool(reveal)
        if reveal != self._reveal:
            self._reveal = reveal
            self._rebuild_image()

    # ---- compose into self.image using fixed _box_size ----
    def _rebuild_image(self):
        w, h = self._box_size
        surf = pygame.Surface((w, h), pygame.SRCALPHA)

        # Background + 2px rounded border
        pygame.draw.rect(surf, self.background_color, (0, 0, w, h), border_radius=4)
        pygame.draw.rect(
            surf, self.border_color, (0, 0, w, h), width=2, border_radius=4
        )

        # Text (left padding)
        left_pad = 10
        text_surf = self.font.render(self._display_text(), self.antialias, self.color)
        text_rect = text_surf.get_rect()
        text_rect.left = left_pad
        text_rect.centery = h // 2
        surf.blit(text_surf, text_rect)

        # Caret (blink)
        if self.cursor_visible:
            cursor_x = min(text_rect.right, w - 2)  # clamp inside box
            pygame.draw.line(
                surf,
                self.color,
                (cursor_x, text_rect.top),
                (cursor_x, text_rect.top + text_rect.height),
                2,
            )

        self.image = surf.convert_alpha()
        self.rect.size = self._box_size  # keep rect size fixed
        self.dirty = 1

    # ---- override: keep fixed size and position, then rebuild ----
    def set_text(self, new_text: str):
        # Preserve position in case Label.set_text mutates rect
        tl = self.rect.topleft
        super().set_text(new_text)
        # Restore fixed geometry
        self.rect.topleft = tl
        self.rect.size = self._box_size
        # Keep caret in range and rebuild
        self.cursor_position = min(self.cursor_position, len(new_text))
        self._rebuild_image()

    # ---- blink + redraw ----
    def update(self, dt: float):
        if self.blinking_cursor:
            self.cursor_timer += dt
            if self.cursor_timer >= 0.5:
                self.cursor_visible = not self.cursor_visible
                self.cursor_timer = 0.0
                self._rebuild_image()

    def draw(self, surface: pygame.Surface):
        surface.blit(self.image, self.rect)

    # ---- input handling ----
    def handle_event(self, event):
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
            from ....peripherals.display import active_profile

            xy = active_profile().to_logical(event)
            self.active = bool(xy) and self.rect.collidepoint(xy)
            if self.active:
                self.cursor_position = len(self.text)
                self._rebuild_image()
            return

        if not self.active or event.type != pygame.KEYDOWN:
            return

        txt = self.text  # read-only is fine

        if event.key == pygame.K_BACKSPACE:
            if self.cursor_position > 0:
                new_txt = txt[: self.cursor_position - 1] + txt[self.cursor_position :]
                self.cursor_position -= 1
                self.set_text(new_txt)

        elif event.key == pygame.K_DELETE:
            if self.cursor_position < len(txt):
                new_txt = txt[: self.cursor_position] + txt[self.cursor_position + 1 :]
                self.set_text(new_txt)

        elif event.key == pygame.K_LEFT:
            if self.cursor_position > 0:
                self.cursor_position -= 1
                self._rebuild_image()

        elif event.key == pygame.K_RIGHT:
            if self.cursor_position < len(self.text):
                self.cursor_position += 1
                self._rebuild_image()

        elif event.unicode and event.key != pygame.K_RETURN:
            new_txt = (
                txt[: self.cursor_position]
                + event.unicode
                + txt[self.cursor_position :]
            )
            self.cursor_position += 1
            self.set_text(new_txt)
