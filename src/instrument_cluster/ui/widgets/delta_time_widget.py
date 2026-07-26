import math

import pygame

from ...core.vehicle.vehicle_bus import VehicleBus
from ...signals.signal_keys import SignalKey
from ...telemetry.mode import DiffReferenceMode
from ..colors import Color
from ..utils import FontFamily, su
from ..widgets import Widget

# Header per active diff reference mode, so a mode switch is visible even
# when the two references happen to read the same delta at the current spot.
_HEADER_DEFAULT = "Time  Diff"
_MODE_HEADERS = {
    DiffReferenceMode.FASTEST.value: "Time  Diff  [Best]",
    DiffReferenceMode.PREVIOUS.value: "Time  Diff  [Prev]",
}


class DeltaTimeWidget(Widget):
    """
    Panel with a header text and a centered dynamic value underneath.
    Redraws only when the dynamic value changes.

    It features the "Segmented Performance Tracker" design:
    - Slanted bars (parallelograms)
    - Gradient fade-out effect
    - Center-out animation
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        header_text: str = _HEADER_DEFAULT,
        anchor: str = "center",
        font_value_size: int = 74,
        font_value_family: FontFamily = FontFamily.D_DIN_EXP,
        show_border: bool = True,
        antialias: bool = True,
        font_scale: float = 1.0,
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
        )

        self._lap_index = -1

        self._seg_width = su(12)  # Width of a single segment
        self._seg_height = su(20)  # Height of the segments
        self._seg_gap = su(3)  # Gap between segments
        self._seg_slant = su(8)  # Slant offset (in pixels)
        self._seg_ms = 100  # Milliseconds per segment
        self._max_segments = 10  # Max number of segments per side
        self._y_offset = su(8)  # Vertical spacing below the text

        # Lift the value above the value area's center so the segment
        # tracker underneath gets more room (positive = up, see
        # Widget._render_value).
        self.value_offset_y = su(16)

        self._last_rendered_value: float | None = None
        self._last_value_str: str = ""

        self.set_value()
        self.visible = 1
        self.dirty = 2

    def reset(self) -> None:
        """Reset UI state."""
        self.set_value()
        self._lap_index = -1

    def update(self, bus: VehicleBus, dt: float):
        packet = bus.frame
        if packet is None:
            return

        self._sync_header(bus)

        lap_count = int(getattr(packet, "lap_count", 0) or 0)

        if lap_count in (0, None):
            if self._lap_index != -1:
                self.reset()
            return

        if lap_count != self._lap_index:
            self._lap_index = lap_count

        stable_delta = bus.signals.get("delta_diff_stable")

        if stable_delta is not None and math.isfinite(stable_delta):
            self.set_value(float(stable_delta))

    def _sync_header(self, bus: VehicleBus) -> None:
        mode = bus.signals.get(SignalKey.DELTA_REFERENCE_MODE)
        header = _MODE_HEADERS.get(mode, _HEADER_DEFAULT)
        if header != self.header_text:
            self.set_header(header)
            # The rebuilt base image carries no value — invalidate the
            # last-rendered state so the next set_value repaints in full.
            self._last_value_str = ""
            self._last_rendered_value = None

    def set_value(self, value: float | None = None):
        # Optimization: If value is effectively unchanged, skip logic. The
        # display only resolves centiseconds (`05.2f`) and the segment tracker
        # snaps to 0.1 s, so an absolute tolerance of half a centisecond skips
        # redraws that can't change a pixel. rel_tol alone never trips near 0.
        if value is not None and self._last_rendered_value is not None:
            if math.isclose(
                value, self._last_rendered_value, rel_tol=1e-5, abs_tol=0.005
            ):
                return

        value_str, color = self._format_delta(value)

        # 1. Text changed? Redraw everything.
        if value_str != self._last_value_str:
            self._last_value_str = value_str
            value_area = self._render_value(value_str, color)
            self._render_segmented_tracker(value_area, value)
            self.dirty = 1
            self._last_rendered_value = value

        # 2. Text is same, but value changed enough to affect segments? Redraw.
        elif value is not None:
            value_area = self._render_value(value_str, color)
            self._render_segmented_tracker(value_area, value)
            self.dirty = 1
            self._last_rendered_value = value

    def _format_delta(self, value: float | None):
        if value is None or not math.isfinite(value):
            return "", self.text_color

        # Text color: Green for negative (gain), Red for positive (loss)
        color = Color.GREEN.rgb() if value < 0.0 else Color.LIGHT_RED.rgb()
        txt = f"{abs(value):05.2f}"
        return txt, color

    def _blend_color(
        self, base_color: tuple[int, int, int], factor: float
    ) -> tuple[int, int, int]:
        """
        Dims a color by a specific factor.
        factor: 1.0 = Original color, 0.0 = Black
        """
        return (
            int(base_color[0] * factor),
            int(base_color[1] * factor),
            int(base_color[2] * factor),
        )

    def _render_segmented_tracker(
        self, area: pygame.Rect, current_value: float | None
    ) -> None:
        """
        Draws a segmented performance tracker:
        - Slanted polygons (parallelograms)
        - Brightness gradient (Center = Bright -> Outer = Darker)
        - Builds outwards from the center
        """
        if current_value is None or not math.isfinite(current_value):
            return

        # 1. Calculate number of active segments
        # e.g., 0.25s / 0.05 = 5 segments
        cs = round(
            abs(current_value) * 100
        )  # snap to centiseconds, matching display precision
        num_active = cs // (self._seg_ms // 10)

        # Clamp to max segments
        if num_active > self._max_segments:
            num_active = self._max_segments

        is_gain = current_value < 0.0

        # Select base color
        base_color = Color.GREEN.rgb() if is_gain else Color.LIGHT_RED.rgb()

        # Start Y-position: right below the value text. The text is drawn
        # centered in the value area and lifted by value_offset_y, so the
        # segments track it instead of assuming the image center.
        text_center_y = area.centery - self.value_offset_y
        text_half_height = su(self.font_value_size) // 2

        y_top = text_center_y + text_half_height + self._y_offset
        y_bottom = y_top + self._seg_height

        center_x = area.centerx

        # 2. Draw segments
        for i in range(num_active):
            # Gradient calculation:
            # i=0 (inner) -> Factor 1.0 (Bright)
            # i=max (outer) -> Factor 0.4 (Darker)
            # Adjust the 0.6 factor to change gradient intensity
            fade_factor = 1.0 - (i / self._max_segments) * 0.6
            seg_color = self._blend_color(base_color, fade_factor)

            # Calculate X-offset (from center outwards)
            offset = self._seg_gap + (i * (self._seg_width + self._seg_gap))

            if is_gain:
                # Build to the LEFT (Green)
                # We define the RIGHT edge of the segment and calculate backwards
                right_edge = center_x - offset
                left_edge = right_edge - self._seg_width

                # Coordinates for polygon (Parallelogram / Slanted)
                # Slant to the right (like italic text)
                p1 = (left_edge + self._seg_slant, y_top)  # Top Left
                p2 = (right_edge + self._seg_slant, y_top)  # Top Right
                p3 = (right_edge, y_bottom)  # Bottom Right
                p4 = (left_edge, y_bottom)  # Bottom Left

            else:
                # Build to the RIGHT (Red)
                left_edge = center_x + offset
                right_edge = left_edge + self._seg_width

                p1 = (left_edge + self._seg_slant, y_top)  # Top Left
                p2 = (right_edge + self._seg_slant, y_top)  # Top Right
                p3 = (right_edge, y_bottom)  # Bottom Right
                p4 = (left_edge, y_bottom)  # Bottom Left

            # Draw the polygon
            pygame.draw.polygon(self.image, seg_color, [p1, p2, p3, p4])
