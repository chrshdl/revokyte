import math

import pygame

from ...core.vehicle.vehicle_bus import VehicleBus
from ...signals.signal_keys import DeltaState, SignalKey
from ...telemetry.mode import DiffReferenceMode
from ..colors import Color
from ..skins.schema import DeltaStyle
from ..utils import FontFamily, load_font_px, su
from ..widgets import Widget

# Header per active diff reference mode, so a mode switch is visible even
# when the two references happen to read the same delta at the current spot.
#
# Built from DiffReferenceMode.label — the same string Setup's Reference Lap
# dropdown shows — so one setting can never be named two ways (the dash once
# read "[Best]" for what Setup called "fastest"). The longest today is
# "[Previous]" at 200 px, inside the 332 px header.
_HEADER_DEFAULT = "Time  Diff"
_MODE_HEADERS = {
    mode.value: f"{_HEADER_DEFAULT}  [{mode.label}]" for mode in DiffReferenceMode
}

# GT3-dash vocabulary shown in place of the number when there is no delta.
# A blank gauge is ambiguous — it reads the same as a broken one — so every
# reason gets its own word, and the driver learns which wait they are in.
_STATE_TEXT = {
    DeltaState.BEACON: "BEACON",    # waiting for the start/finish crossing
    DeltaState.REF_LAP: "REF LAP",  # this lap is being recorded as reference
    DeltaState.NO_REF: "NO REF",    # an established reference was discarded
}

# The state words are longer than the 5-char "00.42" the value font is sized
# for, so they get their own face rather than being squeezed through the
# digit-metrics path (which allots every glyph a digit's width).
#
# Same family as the value itself, so the slot reads consistently whether it
# holds a number or a word — and because PIXEL_TYPE (the *header* face) draws
# a stray apex pixel on "A" that looks like a rendering fault at this size.
# 46 design px sits the widest token, "BEACON" (185 px), comfortably inside
# the 336 px panel without crowding the number's optical weight.
_STATE_FONT_SIZE = 46
_STATE_FONT_FAMILY = FontFamily.D_DIN_EXP

# Lift of the state word above the value area's centre, in design px.
#
# The value area starts below the header, so its centre sits low in the
# panel — geometrically correct, optically not: the eye centres the word
# against the *box*, and reads a value-area-centred word as sitting low.
# The number doesn't need this (it has value_offset_y plus the segment
# tracker beneath it to balance the box); a lone word does.
_STATE_OFFSET_Y = 10


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
        *,
        delta_style: DeltaStyle | None = None,
        state_font_size: int | None = None,
        state_font_family: FontFamily | None = None,
        header_font_size: int | None = None,
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
            header_font_size=header_font_size,
        )

        self._lap_index = -1

        if delta_style is not None:
            # Skinned construction: native pixels straight from the skin.
            self._seg_width = delta_style.seg_width
            self._seg_height = delta_style.seg_height
            self._seg_gap = delta_style.seg_gap
            self._seg_slant = delta_style.seg_slant
            self._y_offset = delta_style.seg_y_offset
            self.value_offset_y = delta_style.value_offset_y
            self.state_offset_y = delta_style.state_offset_y
        else:
            # Spec-space (custom dashboard / legacy) construction: segment
            # geometry follows the panel scale, the state offset also the
            # rect ratio carried in font_scale.
            self._seg_width = su(12)  # Width of a single segment
            self._seg_height = su(20)  # Height of the segments
            self._seg_gap = su(3)  # Gap between segments
            self._seg_slant = su(8)  # Slant offset (in pixels)
            self._y_offset = su(8)  # Vertical spacing below the text
            # Lift the value above the value area's center so the segment
            # tracker underneath gets more room (positive = up, see
            # Widget._render_value).
            self.value_offset_y = su(16)
            self.state_offset_y = round(_STATE_OFFSET_Y * self.font_scale)
        self._seg_ms = 100  # Milliseconds per segment
        self._max_segments = 10  # Max number of segments per side

        self._last_rendered_value: float | None = None
        self._last_value_str: str = ""
        if state_font_size is None:
            # Spec-space default scaled with the rect (font_scale carries
            # the panel scale on the custom path, see registry.py).
            state_font_size = max(1, round(_STATE_FONT_SIZE * self.font_scale))
        if state_font_family is None:
            state_font_family = _STATE_FONT_FAMILY
        self._state_font = load_font_px(state_font_size, state_font_family)

        self.set_value()
        self.visible = 1

    def reset(self) -> None:
        """Clear the gauge completely.

        Not used by ``update()``: leaving a timed lap is not a blank gauge
        but a BEACON state, so that path renders the state word instead.
        Kept for callers that want the panel genuinely empty.
        """
        self.set_value()
        self._lap_index = -1

    def update(self, bus: VehicleBus, dt: float):
        packet = bus.frame
        if packet is None:
            return

        self._sync_header(bus)

        lap_count = int(getattr(packet, "lap_count", 0) or 0)
        self._lap_index = lap_count if lap_count else -1

        stable_delta = bus.signals.get(SignalKey.DELTA_DIFF_STABLE)

        if not lap_count or stable_delta is None or not math.isfinite(stable_delta):
            # There is no delta to show. Name the reason instead of holding
            # the previous number: a delta left over from an earlier lap,
            # reference or track is indistinguishable from a live one, which
            # is the one thing this gauge must never be.
            self.set_state(bus.signals.get(SignalKey.DELTA_STATE))
            return

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

    def set_state(self, state: str | None) -> None:
        """Show why there is no delta, or clear the gauge when there is no
        reason to give (``state`` None / unrecognised)."""
        text = _STATE_TEXT.get(state, "")
        if text == self._last_value_str:
            return

        self._last_value_str = text
        # No number is on screen any more, so the numeric fast-path must not
        # compare against a value that is no longer displayed.
        self._last_rendered_value = None
        self._render_state(text)
        self.dirty = 1

    def _value_area(self) -> pygame.Rect:
        """The panel area below the header, where the value or state word
        is centred (mirrors the geometry in Widget._render_value)."""
        inner_left = self.border_width
        inner_top = max(self._header_bottom + self.header_margin, self.border_width)
        return pygame.Rect(
            inner_left,
            inner_top,
            self.w - self.border_width - inner_left,
            self.h - self.border_width - inner_top,
        )

    def _render_state(self, text: str) -> None:
        """Paint a state word (or nothing) over a clean base image."""
        self.image.blit(self._base_image, (0, 0))
        if not text:
            return

        # Dimmed: it is status, not data, and must not read as a measurement.
        surf = self._state_font.render(text, self.antialias, Color.LIGHT_GREY.rgb())
        area = self._value_area()
        # Not value_offset_y: that lift is sized for the number, which also
        # has the segment tracker under it. A lone word needs a smaller
        # nudge off the value area's centre — see _STATE_OFFSET_Y.
        self.image.blit(
            surf,
            surf.get_rect(center=(area.centerx, area.centery - self.state_offset_y)),
        )

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
        # font_value_size is final pixels on every path (the base class
        # resolves scaling at construction), so no further scaling here.
        text_half_height = self.font_value_size // 2

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
