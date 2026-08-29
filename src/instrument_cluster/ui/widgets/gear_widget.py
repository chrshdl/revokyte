from __future__ import annotations

import pygame

from ...core.vehicle.vehicle_bus import VehicleBus
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...telemetry.models import TelemetryFrame
from ..utils import FontFamily, top_shadow_gradient
from ..widgets import Widget


class GearWidget(Widget):
    """
    Panel with a header text and a centered dynamic value underneath.
    Redraws only when the dynamic value changes.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = "Gear",
        anchor: str = "center",
        header_margin: int = 3,
        font_value_size: int = 264,
        font_value_family: FontFamily | None = None,
        show_border: bool = False,
        antialias: bool = True,
        font_scale: float = 1.0,
        header_font_size: int | None = None,
        value_color: tuple[int, int, int] | None = None,
        text_color: tuple[int, int, int] | None = None,
        bg_gradient_top: tuple[int, int, int] | None = None,
        bg_gradient_bottom: tuple[int, int, int] | None = None,
        border_color: tuple[int, int, int] | None = None,
        border_width: int | None = None,
        border_radius: int | None = None,
        shadow_depth_pct: int = 0,
        shadow_color: tuple[int, int, int] | None = None,
        bevel_light: tuple[int, int, int] | None = None,
        bevel_dark: tuple[int, int, int] | None = None,
        bevel_width: int = 0,
    ):
        # Before super(): Widget builds the background gradient inside its
        # __init__, and _create_background_gradient() below reads this.
        self._shadow_depth_pct = shadow_depth_pct
        self._shadow_color = shadow_color
        super().__init__(
            rect=rect,
            header_text=header_text,
            anchor=anchor,
            header_margin=header_margin,
            font_value_size=font_value_size,
            font_value_family=font_value_family,
            show_border=show_border,
            antialias=antialias,
            font_scale=font_scale,
            header_font_size=header_font_size,
            value_color=value_color,
            text_color=text_color,
            bg_gradient_top=bg_gradient_top,
            bg_gradient_bottom=bg_gradient_bottom,
            border_color=border_color,
            border_width=border_width,
            border_radius=border_radius,
        )
        self._bevel_light = bevel_light
        self._bevel_dark = bevel_dark
        self._bevel_width = bevel_width
        self._draw_bevel()
        self._refresh_base_image()
        self.set_value(-1)

    def _create_background_gradient(
        self,
        top_color: tuple[int, int, int] | None,
        bottom_color: tuple[int, int, int] | None,
    ):
        """An inset shadow along the top edge, not a full-height ramp.

        The panel this imitates is flat over most of its body with the
        darkening confined to the top fifth; a linear ramp leaves the top too
        light and the middle too dark. ``top_color`` is the shadow tone,
        ``bottom_color`` the flat fill, and a depth of 0 gives a flat panel —
        which is how the default skins keep their plain black gear box.
        """
        if top_color is None or bottom_color is None:
            return None
        return top_shadow_gradient(
            (self.w, self.h),
            self._shadow_color or top_color,
            top_color,
            self._shadow_depth_pct,
            fill_bottom_color=bottom_color,
        )

    def _draw_bevel(self) -> None:
        """A 3D bevel: light along the top and left, dark along the bottom
        and right, so the panel reads as a physical screen in a frame.

        Drawn along the STRAIGHT spans between the corner arcs. pygame has no
        way to stroke part of a rounded rect, and the corners are where the
        two tones would meet and cancel anyway, so nothing is lost by leaving
        them to the border underneath.
        """
        if self._bevel_width <= 0 or not (self._bevel_light and self._bevel_dark):
            return
        w, h = self.w, self.h
        r = max(self.border_radius, 0)
        inset = self.border_width
        bw = self._bevel_width
        for i in range(bw):
            o = inset + i
            if o >= min(w, h) // 2:
                break
            # top + left: highlight
            pygame.draw.line(self.image, self._bevel_light, (r, o), (w - r - 1, o))
            pygame.draw.line(self.image, self._bevel_light, (o, r), (o, h - r - 1))
            # bottom + right: shadow
            pygame.draw.line(
                self.image, self._bevel_dark, (r, h - 1 - o), (w - r - 1, h - 1 - o)
            )
            pygame.draw.line(
                self.image, self._bevel_dark, (w - 1 - o, r), (w - 1 - o, h - r - 1)
            )

    def set_value(self, value: int):
        if value == 0:
            gear_str = "R"
        elif value == -1:
            gear_str = "N"
        elif value == -2:
            gear_str = "P"
        else:
            gear_str = str(value)

        if gear_str != self._last_value_str:
            self._last_value_str = gear_str
            self._render_value(gear_str)
            self.dirty = 1

    def update(self, bus: VehicleBus, dt: float):
        frame: TelemetryFrame = bus.frame
        if frame is None:
            return

        flags = getattr(frame, "flags", None)
        car_on_track = bool(getattr(flags, "car_on_track", False))
        if car_on_track:
            gear = int(getattr(frame, "current_gear", 0) or 0)
        else:
            gear = -2  # P
        self.set_value(gear)
