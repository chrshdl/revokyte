from typing import Optional

import pygame

from ...core.vehicle.vehicle_bus import VehicleBus
from ..utils import FontFamily
from ..widgets import Widget


class TrackNameWidget(Widget):
    """
    Panel with a header and the current track name underneath.

    The name comes from ``TrackSignal`` via ``bus.signals["track_name"]``.
    Redraws only when the name changes. Unlike the lap-time widgets, the value
    is rendered as a single proportional string (scaled down to fit the panel)
    rather than through the base digit-slot renderer, which is monospaced for
    numeric readouts.
    """

    # Shown before TrackSignal has published a name. TrackSignal emits "Tap to Set"
    # until the user picks a track via the widget, then the chosen track's name.
    _DEFAULT_TRACK_TEXT = "—"

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = "Track  Name",
        anchor: str = "center",
        font_value_size: int = 40,
        font_value_family: FontFamily = FontFamily.D_DIN_EXP,
        show_border: bool = True,
        antialias: bool = True,
        font_scale: float = 1.0,
        value_color: tuple[int, int, int] | None = None,
    ):
        super().__init__(
            rect=rect,
            header_text=header_text,
            anchor=anchor,
            font_value_size=font_value_size,
            font_value_family=font_value_family,
            show_border=show_border,
            antialias=antialias,
            font_scale=font_scale,
            value_color=value_color,
        )

        self.set_value(TrackNameWidget._DEFAULT_TRACK_TEXT)
        self.visible = 1
        self.dirty = 2

    def set_value(self, name: Optional[str] = None):
        text = (name or "").strip() or TrackNameWidget._DEFAULT_TRACK_TEXT

        if text != self._last_value_str:
            self._last_value_str = text
            self._render_name(text)
            self.dirty = 1

    def reset(self) -> None:
        self.set_value(TrackNameWidget._DEFAULT_TRACK_TEXT)

    def update(self, bus: VehicleBus, dt: float):
        if bus is None:
            return
        self.set_value(bus.signals.get("track_name"))

    def _render_name(self, text: str) -> None:
        # Restore border + header, clearing any previously drawn name.
        self.image.blit(self._base_image, (0, 0))

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
