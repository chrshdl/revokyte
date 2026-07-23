import math

import pygame

from ...core.vehicle.vehicle_bus import VehicleBus
from ...telemetry.models import TelemetryFrame
from ..colors import Color
from ..utils import FontFamily, load_font
from ..widgets import Widget


class RpmWidget(Widget):
    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = "",  # TODO: do we need it?
        anchor: str = "center",
        header_margin: int = 3,
        *,
        max_rpm: int = 8000,
        redline_rpm: int = 6500,
        min_px_per_tick: int = 3,
        major_factor: int = 10,
        show_border: bool = False,
        antialias: bool = True,
        font_scale: float = 1.0,
    ):
        super().__init__(
            rect=rect,
            header_text=header_text,
            anchor=anchor,
            header_margin=header_margin,
            font_value_size=24,  # used only if we render text via _render_value
            show_border=show_border,
            antialias=antialias,
            font_scale=font_scale,
        )

        # RPM configuration
        self._max_rpm = int(max_rpm)
        self._redline_rpm = int(redline_rpm)
        self._alert_min = int(redline_rpm)  # will be updated from rpm_alert.min
        self._alert_max = int(max_rpm)  # will be updated from rpm_alert.max

        self.current_rpm = 0

        # tick configuration
        self._min_px_per_tick = max(1, int(min_px_per_tick))
        self._major_factor = max(2, int(major_factor))
        self._tick_step_rpm = 100
        self._major_step_rpm = 1000
        self._tick_count = 0

        # for 0---.---.---.---max labels (follow the widget's font scale)
        label_size = max(1, round(18 * self.font_scale))
        self._label_font = load_font(
            size=label_size, family=FontFamily.D_DIN_EXP_BOLD
        )  # FIXME: was 22
        self._label_major_font = load_font(
            size=label_size, family=FontFamily.D_DIN_EXP_BOLD
        )

        # Cached ticks+labels layer and last-drawn segment rects: the scale
        # only changes with the RPM configuration, so per value change only
        # the segment rects are drawn over the cached surface (redrawing the
        # full scale cost ~0.3 ms per 60 Hz frame on the Pi).
        self._scale_key = None
        self._scale_surface = None
        self._last_segments = None

        # first draw
        self.set_value(0)

    def set_value(self, value: int):
        """
        Set current RPM and redraw the bar.
        """
        rpm = int(value or 0)
        rpm = max(0, min(rpm, self._max_rpm))

        if rpm == self.current_rpm and self._last_value_str is not None:
            # nothing changed, skip redraw
            return

        self.current_rpm = rpm

        # Redraw the bar over the cached scale; skip when no pixel moved.
        if self._draw_rpm_bar():
            self.dirty = 1

    def update(self, bus: VehicleBus, dt: float):
        frame: TelemetryFrame = bus.frame
        if frame is None:
            return
        """
        Update thresholds from rpm_alert and set current RPM from TelemetryFrame.
        """
        if frame is None:
            self.set_value(0)
            return

        rpm_alert = getattr(frame, "rpm_alert", None)
        if rpm_alert:
            # Bounds.min -> rev warning (redline)
            # Bounds.max -> limiter/max usable RPM
            new_redline = int(getattr(rpm_alert, "min", self._redline_rpm))
            new_max = int(getattr(rpm_alert, "max", self._max_rpm))

            new_max = max(1, new_max)
            new_redline = max(0, min(new_redline, new_max))

            self._redline_rpm = new_redline
            self._max_rpm = new_max
            self._alert_min = self._redline_rpm
            self._alert_max = self._max_rpm

        rpm = int(getattr(frame, "engine_rpm", 0) or 0)
        self.set_value(rpm)

    def _normalize(self, value: int) -> int:
        """
        Show RPM in thousands (9000 -> 9, 10250 -> 10, etc.).
        """
        return int(round(value * 0.001))

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

    def _recompute_ticks(self, bar_width: int):
        """
        Compute minor / major tick spacing based on the available bar width and max RPM.
        """
        max_minor_ticks_by_pixels = max(1, bar_width // self._min_px_per_tick)
        raw_step = max(1, math.ceil(self._max_rpm / max_minor_ticks_by_pixels))
        step_100s = max(1, math.ceil(raw_step / 100))
        self._tick_step_rpm = step_100s * 100
        self._major_step_rpm = self._tick_step_rpm * self._major_factor
        self._tick_count = math.ceil(self._max_rpm / self._tick_step_rpm)

    def _draw_rpm_bar(self) -> bool:
        """
        Draws:
          - horizontal segmented bar (normal / warning / redline)
          - ticks under the bar
          - "0" and max labels
        onto self.image. Ticks and labels depend only on the RPM
        configuration and geometry, so they live in a cached scale surface;
        a value change re-blits that surface and draws the (up to three)
        segment rects on top. Returns True when pixels changed.
        """
        value_area = self._compute_value_area()

        # Layout inside value_area
        padding_x = 6
        padding_y = 2

        bar_left = value_area.left + padding_x
        bar_right = value_area.right - padding_x
        bar_width = max(1, bar_right - bar_left)

        # Reserve some vertical space: bar + ticks + labels
        total_h = value_area.height
        bar_height = max(6, int(total_h * 0.4))
        bar_top = value_area.top + padding_y

        # Helper to convert rpm -> x coordinate
        def _rpm_to_x(rpm: int) -> int:
            t = 0.0 if self._max_rpm == 0 else (rpm / float(self._max_rpm))
            return bar_left + round(t * bar_width)

        scale_key = (
            self._max_rpm,
            self._redline_rpm,
            value_area.x,
            value_area.y,
            value_area.w,
            value_area.h,
        )
        if scale_key != self._scale_key:
            # Recompute tick spacing for current width
            self._recompute_ticks(bar_width)
            self._scale_surface = self._render_scale(
                bar_left, bar_right, bar_top, bar_height, _rpm_to_x
            )
            self._scale_key = scale_key
            self._last_segments = None

        # --- Segments ---
        rpm = self.current_rpm
        alert_zone = min(rpm, self._alert_min)
        yellow_zone = max(
            0, min(rpm - self._alert_min, self._redline_rpm - self._alert_min)
        )
        red_zone = max(0, rpm - self._redline_rpm)

        segments = []
        # Normal/alert zone (placeholder green-ish)
        if alert_zone > 0:
            segments.append(
                (
                    Color.GREY.rgb(),  # you can swap this for a real green
                    (bar_left, bar_top, _rpm_to_x(alert_zone) - bar_left, bar_height),
                )
            )
        # Yellow / pre-redline zone
        if yellow_zone > 0:
            start_x = _rpm_to_x(self._alert_min)
            segments.append(
                (
                    Color.GREY.rgb(),  # placeholder yellow
                    (
                        start_x,
                        bar_top,
                        _rpm_to_x(self._alert_min + yellow_zone) - start_x,
                        bar_height,
                    ),
                )
            )
        # Red limiter zone
        if red_zone > 0:
            start_x = _rpm_to_x(self._redline_rpm)
            segments.append(
                (
                    Color.LIGHT_RED.rgb(),
                    (
                        start_x,
                        bar_top,
                        _rpm_to_x(self._redline_rpm + red_zone) - start_x,
                        bar_height,
                    ),
                )
            )

        # Keep a "value string" so Widget-style change detection still works
        self._last_value_str = str(self.current_rpm)

        if segments == self._last_segments:
            # sub-pixel RPM change: nothing on screen moves
            return False
        self._last_segments = segments

        self.image.blit(self._scale_surface, value_area.topleft, area=value_area)
        for color, rect in segments:
            pygame.draw.rect(self.image, color, pygame.Rect(rect))
        return True

    def _render_scale(self, bar_left, bar_right, bar_top, bar_height, _rpm_to_x):
        """Background + ticks + labels for the current RPM configuration, at
        widget-image coordinates (only the value area is ever blitted)."""
        surf = pygame.Surface((self.w, self.h)).convert_alpha()
        surf.fill(self.bg_color)

        # --- Ticks below bar ---
        ticks_y1 = bar_top + bar_height
        minor_count = self._tick_count + 1
        sparse_factor = 2

        def _draw_tick(tick_rpm: int, y1: int):
            tick_x = _rpm_to_x(tick_rpm)
            is_end = tick_rpm >= self._max_rpm
            is_major = is_end or ((tick_rpm % self._major_step_rpm) == 0)
            y2 = y1 + (7 if is_major else 3)
            width = 3 if is_major else 2
            tick_color = (
                Color.LIGHT_RED.rgb()
                if tick_rpm >= self._redline_rpm
                else Color.LIGHT_GREY.rgb()
            )
            pygame.draw.line(surf, tick_color, (tick_x, y1), (tick_x, y2), width)

        for i in range(0, minor_count, sparse_factor):
            tick_rpm = min(i * self._tick_step_rpm, self._max_rpm)
            _draw_tick(tick_rpm, ticks_y1)

        if (minor_count - 1) % sparse_factor != 0:
            _draw_tick(self._max_rpm, ticks_y1)

        # --- Labels ---
        label_y = ticks_y1 + 6

        # 1) Left-most label: 0
        zero_surf = self._label_font.render("0", self.antialias, Color.LIGHT_GREY.rgb())
        zero_rect = zero_surf.get_rect()
        # left-aligned to bar start to avoid clipping
        zero_rect.midtop = (bar_left, label_y)
        surf.blit(zero_surf, zero_rect)

        # 2) Intermediate major tick labels (exclude 0 and max)
        if self._major_step_rpm > 0:
            tick_rpm = self._major_step_rpm
            while tick_rpm < self._max_rpm:
                tick_x = _rpm_to_x(tick_rpm)
                txt = str(self._normalize(tick_rpm))

                color = (
                    Color.LIGHT_RED.rgb()
                    if tick_rpm >= self._redline_rpm
                    else Color.LIGHT_GREY.rgb()
                )

                label_surf = self._label_major_font.render(txt, self.antialias, color)
                rect = label_surf.get_rect()
                # center under the tick
                rect.midtop = (tick_x, label_y)
                surf.blit(label_surf, rect)

                tick_rpm += self._major_step_rpm

        # 3) Right-most label: max (in thousands)
        max_surf = self._label_font.render(
            str(self._normalize(self._max_rpm)), self.antialias, Color.LIGHT_RED.rgb()
        )
        max_rect = max_surf.get_rect()
        # right-aligned to bar end to avoid clipping
        max_rect.midtop = (bar_right, label_y)
        surf.blit(max_surf, max_rect)

        return surf
