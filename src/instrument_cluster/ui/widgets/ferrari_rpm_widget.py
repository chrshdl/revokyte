from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ...core.vehicle.vehicle_bus import VehicleBus

if TYPE_CHECKING:
    from ...telemetry.models import TelemetryFrame
from ..colors import Color
from ..skins.schema import RpmStyle
from ..utils import FontFamily, load_font_px
from ..widgets import Widget

# Spec-space (1280x720) bar internals, used by the custom-dashboard path
# where font_scale carries the panel scale. Skinned construction passes the
# active skin's style.rpm instead. Reuses RpmWidget's padding fields; the
# tick/label fields aren't used here (ticks/labels are laid out from the
# number scale, not a uniform tick step).
_SPEC_STYLE = RpmStyle(
    padding_x=6,
    padding_y=2,
    tick_major_len=7,
    tick_minor_len=3,
    tick_major_w=3,
    tick_minor_w=2,
    label_gap=6,
)

# The Ferrari 296 GT3 Evo dash prints a fixed 0, 3, 4, 5, 6, 7, 8 sequence
# (1 and 2 are skipped) rather than uniform ticks over the configured max
# RPM. Positions are proportional to the number's value against this fixed
# 0-8 span, which is what gives the wide 0->3 gap and narrow 7->8 gap seen
# on the real cluster.
_SCALE_NUMBERS: tuple[int, ...] = (0, 3, 4, 5, 6, 7, 8)
_SCALE_MAX = 8

_LED_BLOCK_COUNT = 14
_LED_BLOCK_GAP = 2
_LED_BEVEL_INSET = 2


def _shade(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(c * factor))) for c in rgb)


_FRAME_LINE_FADE_PX = 30
_FRAME_LINE_H = 3


def _draw_gradient_hline(
    surf: pygame.Surface,
    y: int,
    x1: int,
    x2: int,
    color: tuple[int, int, int],
    height: int = 1,
    fade_px: int = _FRAME_LINE_FADE_PX,
    inset: int = 12,
) -> None:
    """A horizontal line that fades to black at both ends. Drawn once per
    scale-surface rebuild (cached, not per frame), so a per-pixel column
    loop is cheap here. ``inset`` shortens the line by that many pixels on
    each side before drawing (it does not affect the fade zone width)."""
    x1, x2 = x1 + inset, x2 - inset
    width = max(1, x2 - x1)
    fade_px = max(1, min(fade_px, width // 2))
    for x in range(x1, x2 + 1):
        dist = min(x - x1, x2 - x)
        t = 1.0 if dist >= fade_px else dist / fade_px
        c = tuple(round(ch * t) for ch in color)
        pygame.draw.line(surf, c, (x, y), (x, y + height - 1))


class FerrariRpmWidget(Widget):
    """Discrete, LED-style horizontal tachometer (Ferrari 296 GT3 Evo style).

    Structurally mirrors RpmWidget (init, VehicleBus updates, cached-surface
    strategy, value area) but the visual language is entirely different: a
    fixed 0/3/4/5/6/7/8 number scale over 14 bevelled LED blocks instead of a
    continuous segmented bar with uniform ticks.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = "",
        anchor: str = "center",
        header_margin: int = 3,
        *,
        max_rpm: int = 8000,
        redline_rpm: int = 7000,
        show_border: bool = False,
        antialias: bool = True,
        font_scale: float = 1.0,
        rpm_style: RpmStyle | None = None,
        label_font_size: int | None = None,
        label_font_family: FontFamily = FontFamily.D_DIN_EXP_BOLD,
        header_font_size: int | None = None,
    ):
        super().__init__(
            rect=rect,
            header_text=header_text,
            anchor=anchor,
            header_margin=header_margin,
            font_value_size=24,
            show_border=show_border,
            antialias=antialias,
            font_scale=font_scale,
            header_font_size=header_font_size,
        )
        self._style = rpm_style if rpm_style is not None else _SPEC_STYLE
        # Which palette colors the scale/redline wear comes from the skin —
        # same lookup RpmWidget uses, so this widget follows skin overrides.
        from ..skins import active_skin

        d = active_skin().dashboard
        self._scale_color = Color[d.rpm_scale_color].rgb()
        self._redline_color = Color[d.rpm_redline_color].rgb()
        self._unlit_color = Color.DARKER_GREY.rgb()
        self._outline_color = Color.BLACK.rgb()

        self._max_rpm = int(max_rpm)
        self._redline_rpm = int(redline_rpm)
        self.current_rpm = 0

        if label_font_size is None:
            label_font_size = max(1, round(20 * self.font_scale))
        self._label_font = load_font_px(label_font_size, label_font_family)
        rpm_text_size = max(1, round(label_font_size * 0.55))
        self._rpm_text_font = load_font_px(rpm_text_size, label_font_family)

        # Cached scale layer (numbers, "RPM" text, ticks, framing lines) and
        # last-drawn block state: the scale only changes with RPM
        # configuration/geometry, so per-value redraws only touch the LED
        # block row on top of the cached surface.
        self._scale_key = None
        self._scale_surface = None
        self._last_block_state = None

        self.set_value(0)

    def set_value(self, value: int):
        """Set current RPM and redraw the LED block row."""
        rpm = int(value or 0)
        rpm = max(0, min(rpm, self._max_rpm))

        if rpm == self.current_rpm and self._last_value_str is not None:
            return

        self.current_rpm = rpm

        if self._draw_rpm_bar():
            self.dirty = 1

    def update(self, bus: VehicleBus, dt: float):
        frame: TelemetryFrame = bus.frame
        if frame is None:
            self.set_value(0)
            return

        rpm_alert = getattr(frame, "rpm_alert", None)
        if rpm_alert:
            new_redline = int(getattr(rpm_alert, "min", self._redline_rpm))
            new_max = int(getattr(rpm_alert, "max", self._max_rpm))

            new_max = max(1, new_max)
            new_redline = max(0, min(new_redline, new_max))

            self._redline_rpm = new_redline
            self._max_rpm = new_max

        rpm = int(getattr(frame, "engine_rpm", 0) or 0)
        self.set_value(rpm)

    def _compute_value_area(self) -> pygame.Rect:
        """
        Same idea as Widget._render_value's area:
        region below header and inside border where we can draw our custom content.
        """
        inner_left = self.border_width
        inner_right = self.w - self.border_width
        inner_top = max(self._header_bottom + self.header_margin, self.border_width)
        inner_bottom = self.h - self.border_width

        return pygame.Rect(
            inner_left,
            inner_top,
            inner_right - inner_left,
            inner_bottom - inner_top,
        )

    def _layout(self, value_area: pygame.Rect):
        """Compute the shared geometry both the cached scale layer and the
        per-frame LED block draw need."""
        padding_x = self._style.padding_x
        padding_y = self._style.padding_y

        area_left = value_area.left + padding_x
        area_right = value_area.right - padding_x
        area_width = max(1, area_right - area_left)

        total_h = value_area.height
        number_h = max(10, int(total_h * 0.34))
        tick_h = max(4, int(total_h * 0.14))
        block_h = max(10, int(total_h * 0.36))

        numbers_top = value_area.top + padding_y
        tick_top = numbers_top + number_h
        frame_top_y = tick_top + tick_h
        # Blocks are painted per-frame on top of the cached scale surface,
        # so they must clear the top line's full height (_FRAME_LINE_H) plus
        # a gap — otherwise their opaque outline paints over its bottom rows
        # wherever a block sits, leaving it looking thinner than the bottom
        # line (which already has full clearance below the blocks).
        block_top = frame_top_y + _FRAME_LINE_H + 2
        block_bottom = block_top + block_h
        frame_bottom_y = block_bottom + 2

        def _x_for(n: int) -> int:
            return area_left + round((n / _SCALE_MAX) * area_width)

        return {
            "area_left": area_left,
            "area_right": area_right,
            "area_width": area_width,
            "numbers_top": numbers_top,
            "tick_top": tick_top,
            "frame_top_y": frame_top_y,
            "block_top": block_top,
            "block_h": block_h,
            "block_bottom": block_bottom,
            "frame_bottom_y": frame_bottom_y,
            "x_for": _x_for,
        }

    def _block_rects(self, layout: dict) -> list[pygame.Rect]:
        area_left = layout["area_left"]
        area_width = layout["area_width"]
        block_top = layout["block_top"]
        block_h = layout["block_h"]

        total_gap = _LED_BLOCK_GAP * (_LED_BLOCK_COUNT - 1)
        block_w = max(1.0, (area_width - total_gap) / _LED_BLOCK_COUNT)

        rects = []
        x = float(area_left)
        for _ in range(_LED_BLOCK_COUNT):
            rects.append(pygame.Rect(round(x), block_top, round(block_w), block_h))
            x += block_w + _LED_BLOCK_GAP
        return rects

    def _draw_rpm_bar(self) -> bool:
        value_area = self._compute_value_area()
        layout = self._layout(value_area)

        scale_key = (
            self._max_rpm,
            self._redline_rpm,
            value_area.x,
            value_area.y,
            value_area.w,
            value_area.h,
        )
        if scale_key != self._scale_key:
            self._scale_surface = self._render_scale(value_area, layout)
            self._scale_key = scale_key
            self._last_block_state = None

        block_rects = self._block_rects(layout)
        ratio = 0.0 if self._max_rpm == 0 else self.current_rpm / float(self._max_rpm)
        active_count = max(0, min(_LED_BLOCK_COUNT, round(ratio * _LED_BLOCK_COUNT)))

        block_state = []
        for i in range(_LED_BLOCK_COUNT):
            lit = i < active_count
            block_mid_rpm = ((i + 0.5) / _LED_BLOCK_COUNT) * self._max_rpm
            is_red = block_mid_rpm >= self._redline_rpm
            block_state.append((lit, is_red))
        block_state = tuple(block_state)

        self._last_value_str = str(self.current_rpm)

        if block_state == self._last_block_state:
            return False
        self._last_block_state = block_state

        self.image.blit(self._scale_surface, value_area.topleft, area=value_area)
        for rect, (lit, is_red) in zip(block_rects, block_state):
            if not lit:
                fill_color = self._unlit_color
            else:
                fill_color = self._redline_color if is_red else self._scale_color
            self._draw_led_block(self.image, rect, fill_color)

        return True

    def _draw_led_block(
        self,
        surf: pygame.Surface,
        rect: pygame.Rect,
        fill_color: tuple[int, int, int],
    ):
        """Cheap 3D bevel via plain shape layering (no alpha blending):
        an outer dark outline, an inset fill, and 1px inner-shadow /
        highlight lines on the fill's top-left / bottom-right edges."""
        pygame.draw.rect(surf, self._outline_color, rect)

        inner_rect = rect.inflate(-2 * _LED_BEVEL_INSET, -2 * _LED_BEVEL_INSET)
        if inner_rect.width <= 0 or inner_rect.height <= 0:
            return
        pygame.draw.rect(surf, fill_color, inner_rect)

        shadow_color = _shade(fill_color, 0.55)
        highlight_color = _shade(fill_color, 1.5)

        # inner shadow: top + left edges
        # pygame.draw.line(
        #     surf,
        #     shadow_color,
        #     inner_rect.topleft,
        #     inner_rect.topright,
        #     1,
        # )
        # pygame.draw.line(
        #     surf,
        #     shadow_color,
        #     inner_rect.topleft,
        #     inner_rect.bottomleft,
        #     1,
        # )
        # highlight: bottom + right edges
        # pygame.draw.line(
        #     surf,
        #     highlight_color,
        #     (inner_rect.left, inner_rect.bottom - 1),
        #     (inner_rect.right - 1, inner_rect.bottom - 1),
        #     1,
        # )
        # pygame.draw.line(
        #     surf,
        #     highlight_color,
        #     (inner_rect.right - 1, inner_rect.top),
        #     (inner_rect.right - 1, inner_rect.bottom - 1),
        #     1,
        # )

    def _render_scale(self, value_area: pygame.Rect, layout: dict) -> pygame.Surface:
        """Background + number scale + "RPM" label + ticks + framing lines,
        at widget-image coordinates (only the value area is ever blitted).
        Opaque on purpose — see RpmWidget._render_scale for why."""
        surf = pygame.Surface((self.w, self.h)).convert()
        surf.fill(self.bg_color)

        area_left = layout["area_left"]
        area_right = layout["area_right"]
        numbers_top = layout["numbers_top"]
        tick_top = layout["tick_top"]
        frame_top_y = layout["frame_top_y"]
        frame_bottom_y = layout["frame_bottom_y"]
        x_for = layout["x_for"]

        # --- Framing lines above/below the LED block row, fading to black
        # at both edges (matches the real dash's tapered scale lines) ---
        _draw_gradient_hline(
            surf,
            frame_top_y,
            area_left,
            area_right,
            self._scale_color,
            height=_FRAME_LINE_H,
        )
        _draw_gradient_hline(
            surf,
            frame_bottom_y,
            area_left,
            area_right,
            self._scale_color,
            height=_FRAME_LINE_H,
        )

        # --- Numbers (0, skip 1/2, 3-8) + ticks dropping to the top line ---
        zero_rect = None
        for n in _SCALE_NUMBERS:
            color = self._redline_color if n >= 7 else self._scale_color
            label_surf = self._label_font.render(str(n), self.antialias, color)
            label_rect = label_surf.get_rect(midtop=(x_for(n), numbers_top))
            surf.blit(label_surf, label_rect)
            if n == 0:
                zero_rect = label_rect

            tick_x = label_rect.centerx
            pygame.draw.line(surf, color, (tick_x, tick_top), (tick_x, frame_top_y), 2)

        # --- "RPM" text immediately right of "0", aligned with the numbers ---
        if zero_rect is not None:
            rpm_surf = self._rpm_text_font.render(
                "RPM", self.antialias, self._scale_color
            )
            rpm_rect = rpm_surf.get_rect()
            rpm_rect.midleft = (
                zero_rect.right + max(2, round(4 * self.font_scale)),
                zero_rect.centery,
            )
            surf.blit(rpm_surf, rpm_rect)

        return surf
