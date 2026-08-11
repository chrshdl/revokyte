import pygame

from ...core.vehicle.vehicle_bus import VehicleBus
from ..utils import FontFamily
from ..widgets import Widget


class SlotNameWidget(Widget):
    """Bordered panel showing the active dashboard slot's name.

    Bottom chrome owned by DashboardView, sitting in the footer beside the
    Setup button and right-aligned under the Track Name column. The value is
    the active custom slot's name (Slot 1 is "DEFAULT"), rendered as a single
    proportional string scaled to fit — like TrackNameWidget, not the base
    digit-slot renderer. Hidden while there is no named slot (no provider or
    the built-in default render), like the slot dots.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = "Slot",
        anchor: str = "topleft",
        font_value_size: int = 40,
        font_value_family: FontFamily | None = None,
        value_color: tuple[int, int, int] | None = None,
        show_border: bool = True,
        antialias: bool = True,
        font_scale: float = 1.0,
        header_font_size: int | None = None,
    ):
        super().__init__(
            rect=rect,
            header_text=header_text,
            anchor=anchor,
            font_value_size=font_value_size,
            font_value_family=font_value_family,
            value_color=value_color,
            show_border=show_border,
            antialias=antialias,
            font_scale=font_scale,
            header_font_size=header_font_size,
        )
        # Start hidden: DashboardState pushes the active name via set_value.
        self.visible = 0

    def set_value(self, name: str | None = None):
        text = (name or "").strip()
        if text == self._last_value_str:
            return
        self._last_value_str = text
        self.visible = 1 if text else 0
        self._render_name(text)
        self.dirty = 1

    def reset(self) -> None:
        self.set_value("")

    def update(self, bus: VehicleBus = None, dt: float = 0.0):
        """Static chrome — the active slot name is pushed via set_value."""

    def _render_name(self, text: str) -> None:
        # Restore border + header, clearing any previously drawn name.
        self.image.blit(self._base_image, (0, 0))
        if not text:
            return

        surf = self.font_value.render(
            text, self.antialias, self.value_color or self.text_color
        )

        # Value area below the header.
        inner_top = max(self._header_bottom + self.header_margin, self.border_width)
        avail_w = self.w - 2 * self.border_width - 8
        avail_h = self.h - self.border_width - inner_top

        # Scale the name down proportionally if it's too wide/tall to fit.
        sw, sh = surf.get_size()
        scale = min(
            1.0,
            avail_w / sw if sw else 1.0,
            avail_h / sh if sh else 1.0,
        )
        if scale < 1.0:
            surf = pygame.transform.smoothscale(
                surf, (max(1, int(sw * scale)), max(1, int(sh * scale)))
            )

        rect = surf.get_rect()
        rect.centerx = self.w // 2
        rect.centery = inner_top + avail_h // 2 - self.value_offset_y
        self.image.blit(surf, rect)
