from __future__ import annotations

from typing import Literal

import pygame

from ...colors import Color
from ...skins import active_skin
from .button import AbstractButton, ButtonEvents, ButtonState


class Toggle(AbstractButton):
    """Material-style on/off switch sprite.

    The rect is the touch target; the switch pill is drawn inside it,
    horizontally placed via ``pill_align`` and vertically centered. Tapping
    anywhere in the rect flips the state and posts ``events.selected`` with
    ``checked`` (bool) in the event data — pressed/released fire as usual
    via AbstractButton.
    """


    def __init__(
        self,
        rect,
        events: ButtonEvents,
        checked: bool = False,
        event_data: dict | None = None,
        *,
        pill_align: Literal["left", "center", "right"] = "right",
        pill_pad: int = 20,
        on_color: tuple[int, int, int] | None = None,
        off_color: tuple[int, int, int] | None = None,
        knob_color: tuple[int, int, int] | None = None,
        # None disables the pressed feedback; the sentinel resolves to the
        # palette default at construction (live palette overrides).
        pressed_bg_color: tuple[int, int, int] | None | str = "default",
    ):
        super().__init__(rect, events, event_data)
        self._checked = bool(checked)
        self.pill_align = pill_align
        self.pill_pad = int(pill_pad)
        style = active_skin().style.toggle
        self.on_color = Color[style.on_color].rgb() if on_color is None else on_color
        self.off_color = (
            Color[style.off_color].rgb() if off_color is None else off_color
        )
        self.knob_color = (
            Color[style.knob_color].rgb() if knob_color is None else knob_color
        )
        # Fills the whole rect while pressed (like a row control's pressed
        # glow); None disables the feedback.
        self.pressed_bg_color = (
            Color.DARKER_GREY.rgb()
            if pressed_bg_color == "default"
            else pressed_bg_color
        )

        self._rebuild_image()

    # ----- state --------------------------------------------------------

    @property
    def checked(self) -> bool:
        return self._checked

    def set_checked(self, checked: bool, fire_event: bool = False) -> None:
        checked = bool(checked)
        if checked == self._checked:
            return

        self._checked = checked
        self._on_visual_change()

        if fire_event and getattr(self.events, "selected", None):
            data = dict(self.event_data or {})
            data["checked"] = checked
            pygame.event.post(pygame.event.Event(self.events.selected, data))

    def handle_event(self, event) -> None:
        prev_state = self.state
        super().handle_event(event)

        # A release that landed inside (press wasn't cancelled by dragging
        # off) flips the switch.
        if (
            prev_state in (ButtonState.PRESSED, ButtonState.LONGPRESSED)
            and self.state == ButtonState.RELEASED
        ):
            self.set_checked(not self._checked, fire_event=True)

    # ----- rendering ----------------------------------------------------

    def _on_visual_change(self) -> None:
        self._rebuild_image()
        self.dirty = 1

    def _pill_rect(self) -> pygame.Rect:
        w, h = self.rect.size
        style = active_skin().style.toggle
        tw, th = style.track_w, style.track_h
        pad = self.pill_pad
        if self.pill_align == "left":
            x = pad
        elif self.pill_align == "center":
            x = (w - tw) // 2
        else:
            x = w - pad - tw
        return pygame.Rect(x, (h - th) // 2, tw, th)

    def _rebuild_image(self) -> None:
        surf = pygame.Surface(self.rect.size, pygame.SRCALPHA)

        if self.is_pressed() and self.pressed_bg_color is not None:
            pygame.draw.rect(
                surf, self.pressed_bg_color, surf.get_rect(), border_radius=4
            )

        pill = self._pill_rect()
        track_color = self.on_color if self._checked else self.off_color
        pygame.draw.rect(surf, track_color, pill, border_radius=pill.height // 2)

        knob_r = pill.height // 2 - active_skin().style.toggle.knob_margin
        cy = pill.centery
        cx = (
            pill.right - pill.height // 2
            if self._checked
            else pill.left + pill.height // 2
        )
        pygame.draw.circle(surf, self.knob_color, (cx, cy), knob_r)

        # convert_alpha is faster for blitting, but only available after the
        # display is initialized.
        if pygame.display.get_surface() is not None:
            self.image = surf.convert_alpha()
        else:
            self.image = surf

    def draw(self, surface: pygame.Surface) -> None:
        """
        Manual draw helper (LayeredDirty uses `image`/`rect` directly).
        """
        surface.blit(self.image, self.rect)
