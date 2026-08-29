"""The Skin schema — one hand-tuned geometry set per panel resolution.

A skin holds every layout number for one native resolution, in **logical
pixels** (integers, no scaling applied at the consumer). This replaces the
single 1280x720 design space + ``sx/sy/su`` scaling for the standard HMI:
each supported panel gets its own skin file whose values are authored
directly against that panel, so nothing is anisotropically stretched and
every font size is a hand-picked integer.

The ``sx/sy/su/srect`` helpers in ``ui/utils.py`` are *not* used by skinned
code. They remain the mapping for the custom-dashboard spec space (user
layouts are authored in 1280x720 regardless of panel, see
``ui/widgets/registry.py``) and for not-yet-migrated legacy code.

Every field carries axis metadata (``axis_*`` below) so
``tools/gen_skin_seed.py`` can mechanically seed a new skin from SKIN_1280
by scaling; the seeded file is then hand-tuned. The metadata says how a
value maps between resolutions, not how it is used at runtime:

* ``x`` / ``y``   — horizontal / vertical coordinate or extent
* ``pos``        — an (x, y) pair
* ``size``       — a (w, h) pair
* ``rect``       — an (x, y, w, h) tuple
* ``u``          — uniform length (radius, gap, border) scaled by min(sx, sy)
* ``font``       — font size: uniform scale, snapped to an even integer
* ``font_pixel`` — pixel-font size (Pixeltype): snapped to a multiple of 8
* ``family``     — a font family, stored as the ``FontFamily`` member name
  (a string); resolution-independent, copied verbatim
* ``color``      — a palette reference, stored as the ``Color`` member name
  (a string); widgets pick *which* palette color they wear, the palette
  itself stays global (edited in the editor's Palette mode)
* ``const``      — resolution-independent (counts, ratios); copied verbatim
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields

Rect = tuple[int, int, int, int]
Pos = tuple[int, int]
Size = tuple[int, int]


def _px(axis: str):
    return field(metadata={"axis": axis})


def axis_of(f) -> str:
    """The scaling axis a dataclass field was declared with."""
    return f.metadata.get("axis", "const")


def iter_px_fields(obj):
    """Yield (field, value) pairs for every annotated field of a skin group."""
    for f in fields(obj):
        yield f, getattr(obj, f.name)


@dataclass(frozen=True)
class TireGrid:
    """The 2x2 tire-temperature quad: one origin plus cell/step metrics
    (pre-shift; the right-column shift is applied by the plugin)."""

    origin: Pos = _px("pos")  # center of the top-left cell
    cell: Size = _px("size")
    col_step: int = _px("x")
    row_step: int = _px("y")


@dataclass(frozen=True)
class SlotDots:
    """The dashboard page indicator dots."""

    center: Pos = _px("pos")
    radius: int = _px("u")
    pitch: int = _px("u")


@dataclass(frozen=True)
class DashboardFonts:
    """Value fonts for the standard gauges: size (native px) + family
    (a ``FontFamily`` member name) per gauge."""

    gear: int = _px("font")
    gear_family: str = _px("family")
    speed: int = _px("font")
    speed_family: str = _px("family")
    rpm_label: int = _px("font")
    rpm_label_family: str = _px("family")
    delta: int = _px("font")
    delta_family: str = _px("family")
    delta_state: int = _px("font")
    delta_state_family: str = _px("family")
    tire: int = _px("font")
    tire_family: str = _px("family")
    track: int = _px("font")
    track_family: str = _px("family")
    slot_name: int = _px("font")
    slot_name_family: str = _px("family")
    lap_counter: int = _px("font")
    lap_counter_family: str = _px("family")
    lap_time: int = _px("font")
    lap_time_family: str = _px("family")
    fastest_lap: int = _px("font")
    fastest_lap_family: str = _px("family")
    predicted_lap: int = _px("font")
    predicted_lap_family: str = _px("family")
    fuel: int = _px("font")
    fuel_family: str = _px("family")


@dataclass(frozen=True)
class DashboardSkin:
    """The racing view: gauge rects, chrome, and the status-strip shifts.

    Gauge rects use the same anchor semantics as the plugins that consume
    them (center for the dials/columns, topleft for the lap counter and the
    tire grid cells). Column rects are pre-shift: plugins add ``shift_l`` /
    ``shift_r`` from :class:`LayoutContext` when the bezel status lights
    reserve their strips.
    """

    gear_rect: Rect = _px("rect")  # center anchor
    speed_rect: Rect = _px("rect")
    rpm_rect: Rect = _px("rect")
    delta_rect: Rect = _px("rect")  # right column, pre-shift
    fastest_lap_rect: Rect = _px("rect")  # left column, pre-shift
    predicted_lap_rect: Rect = _px("rect")
    fuel_per_lap_rect: Rect = _px("rect")
    fuel_laps_rect: Rect = _px("rect")
    track_rect: Rect = _px("rect")
    lap_time_rect: Rect = _px("rect")
    lap_counter_rect: Rect = _px("rect")  # topleft anchor
    tire_grid: TireGrid = _px("group")

    # Bezel status-LED strips (Setup toggle) and the column shifts they
    # cause. shift_*_on are the inward shifts while the strips are shown.
    status_strip_w: int = _px("x")
    shift_l_on: int = _px("x")
    shift_r_on: int = _px("x")
    status_light_rect: Rect = _px("rect")  # left strip; right is mirrored
    status_light_dot_spacing: int = _px("y")
    status_light_dot_radius: int = _px("u")

    # Footer chrome.
    footer_y: int = _px("y")
    button_h: int = _px("y")
    setup_button_w: int = _px("x")
    setup_button_font: int = _px("font_pixel")
    setup_button_font_family: str = _px("family")
    setup_button_icon: int = _px("font")
    setup_button_pad_top: int = _px("u")
    # The Setup button sits among the gauges, so its border is skinned like
    # theirs (style.border_*) rather than carrying the 1280 design's stroke
    # onto every panel.
    setup_button_border_width: int = _px("u")
    setup_button_border_radius: int = _px("u")
    slot_name_left_inset: int = _px("x")
    slot_dots: SlotDots = _px("group")

    fonts: DashboardFonts = _px("group")

    # Page-swipe gesture thresholds, in logical px on this panel.
    swipe_min_dx: int = _px("x")
    swipe_max_dy: int = _px("y")

    # Per-widget palette references. The *_color entries recolor each
    # gauge's value text (headers keep the shared style.text_color).
    gear_color: str = _px("color")
    speed_color: str = _px("color")
    fastest_lap_color: str = _px("color")
    predicted_lap_color: str = _px("color")
    lap_time_color: str = _px("color")
    lap_counter_color: str = _px("color")
    track_color: str = _px("color")
    slot_name_color: str = _px("color")
    fuel_per_lap_color: str = _px("color")
    fuel_laps_color: str = _px("color")
    delta_gain_color: str = _px("color")
    delta_loss_color: str = _px("color")
    tire_gradient_top: str = _px("color")
    tire_gradient_bottom: str = _px("color")
    # Which RPM gauge this panel draws: "ferrari" for the 296 GT3 Evo style
    # segmented bar, "classic" for the original needle/scale RpmWidget. A
    # panel-level design choice rather than geometry, so it lives here and not
    # in the plugin: the bar is authored against the 1280 grid and has no
    # per-skin pass on the smaller panels yet.
    rpm_variant: str = _px("const")
    rpm_scale_color: str = _px("color")
    rpm_redline_color: str = _px("color")
    status_light_tc_color: str = _px("color")
    status_light_asm_color: str = _px("color")
    setup_button_border_color: str = _px("color")
    slot_dot_active_color: str = _px("color")
    slot_dot_inactive_color: str = _px("color")


@dataclass(frozen=True)
class DeltaStyle:
    """Segment-tracker geometry inside the delta widget."""

    seg_width: int = _px("u")
    seg_height: int = _px("u")
    seg_gap: int = _px("u")
    seg_slant: int = _px("u")
    seg_y_offset: int = _px("u")
    value_offset_y: int = _px("u")
    state_offset_y: int = _px("u")


@dataclass(frozen=True)
class RpmStyle:
    """RPM bar internals (paddings, tick metrics)."""

    padding_x: int = _px("u")
    padding_y: int = _px("u")
    tick_major_len: int = _px("u")
    tick_minor_len: int = _px("u")
    tick_major_w: int = _px("u")
    tick_minor_w: int = _px("u")
    label_gap: int = _px("u")


@dataclass(frozen=True)
class ScrollbarStyle:
    thumb_color: str = _px("color")
    track_width: int = _px("u")
    track_margin_right: int = _px("x")
    min_thumb_height: int = _px("y")
    track_hit_pad: int = _px("u")
    drag_threshold: int = _px("u")


@dataclass(frozen=True)
class ToggleStyle:
    track_w: int = _px("x")
    track_h: int = _px("y")
    knob_margin: int = _px("u")
    on_color: str = _px("color")
    off_color: str = _px("color")
    knob_color: str = _px("color")


@dataclass(frozen=True)
class WidgetStyle:
    """Shared gauge-frame styling — the values that used to be unscaled
    residue in ``Widget.__init__`` (borders, margins, gaps that stayed at
    1280-px sizes while everything around them shrank)."""

    header_font_size: int = _px("font_pixel")
    header_font_family: str = _px("family")
    bg_color: str = _px("color")
    text_color: str = _px("color")
    border_color: str = _px("color")
    header_margin: int = _px("u")
    value_offset_y: int = _px("u")
    border_width: int = _px("u")
    border_radius: int = _px("u")
    digit_gap: int = _px("u")
    delta: DeltaStyle = _px("group")
    rpm: RpmStyle = _px("group")
    scrollbar: ScrollbarStyle = _px("group")
    toggle: ToggleStyle = _px("group")


@dataclass(frozen=True)
class HeaderSkin:
    """The title + back-button header shared by Setup/Wi-Fi/IP/install views."""

    title_topleft: Pos = _px("pos")
    title_font_size: int = _px("font")
    title_font_family: str = _px("family")
    title_color: str = _px("color")
    line_y: int = _px("y")
    line_color: str = _px("color")
    back_button_size: Size = _px("size")
    back_button_y: int = _px("y")
    back_button_gap: int = _px("x")
    back_button_icon: int = _px("font")  # material-symbols glyph size


@dataclass(frozen=True)
class SetupSkin:
    """The settings row grid (Setup view and the Wi-Fi network list)."""

    row_top: int = _px("y")
    row_pitch: int = _px("y")
    row_height: int = _px("y")
    row_font_size: int = _px("font")
    row_font_family: str = _px("family")
    icon_x: int = _px("x")
    icon_size: int = _px("font")
    label_x: int = _px("x")
    label_dy: int = _px("y")
    value_x: int = _px("x")
    dropdown_x: int = _px("x")
    separator_inset: int = _px("x")
    separator_width: int = _px("u")
    separator_clearance: int = _px("u")
    chevron_icon_size: int = _px("font")  # row-button trailing chevron
    row_text_color: str = _px("color")
    separator_color: str = _px("color")
    visible_network_cells: int = _px("const")


@dataclass(frozen=True)
class KeyboardSkin:
    """The on-screen QWERTY keyboard (Wi-Fi password entry)."""

    key_w: int = _px("x")
    key_h: int = _px("y")
    gap: int = _px("x")
    top: int = _px("y")
    row_step: int = _px("y")
    special_w: int = _px("x")
    space_w: int = _px("x")
    pw_row_y: int = _px("y")
    pw_row_h: int = _px("y")
    key_font: int = _px("font")
    key_font_family: str = _px("family")
    small_font: int = _px("font")
    small_font_family: str = _px("family")
    key_text_color: str = _px("color")
    ok_color: str = _px("color")
    pw_font: int = _px("font")  # password field text
    pw_font_family: str = _px("family")
    # Scan-phase chrome and the manual-SSID form.
    rescan_size: Size = _px("size")
    rescan_font: int = _px("font_pixel")
    rescan_font_family: str = _px("family")
    manual_label_font: int = _px("font_pixel")
    manual_label_font_family: str = _px("family")
    manual_field_font: int = _px("font")
    manual_field_font_family: str = _px("family")
    manual_ssid_label_pos: Pos = _px("pos")
    manual_pw_label_pos: Pos = _px("pos")
    manual_field_rect: Rect = _px("rect")  # the SSID field
    manual_pw_left: int = _px("x")


@dataclass(frozen=True)
class NumpadSkin:
    """The EnterIP soft numpad and recent-connections column."""

    buttons_per_row: int = _px("const")
    button_dims: Size = _px("size")
    button_margin: int = _px("u")
    offset: Pos = _px("pos")
    recent_position: Pos = _px("pos")
    recent_per_row: int = _px("const")
    recent_dims: Size = _px("size")
    recent_margin: int = _px("u")
    recent_offset: Pos = _px("pos")
    key_font: int = _px("font")
    key_font_family: str = _px("family")
    field_rect: Rect = _px("rect")  # the IP text field
    field_font: int = _px("font")
    field_font_family: str = _px("family")
    del_rect: Rect = _px("rect")
    ok_rect: Rect = _px("rect")
    recent_label_font: int = _px("font")  # Pixeltype, but 46 by design
    recent_label_font_family: str = _px("family")
    ok_color: str = _px("color")
    del_color: str = _px("color")


@dataclass(frozen=True)
class OverlaySkin:
    """Overlay windows: the status pills and the feed-update card.

    The ``wifi_pill_*`` group is the shared status-pill geometry — the
    Wi-Fi connecting note and the no-telemetry alert both render through
    it (see ui/status_pill.py); only their border color fields differ.
    """

    wifi_pill_height: int = _px("y")
    wifi_pill_center_y: int = _px("y")
    wifi_pill_pad_x: int = _px("x")
    wifi_pill_font: int = _px("font")
    wifi_pill_font_family: str = _px("family")
    feed_card_size: Size = _px("size")
    feed_card_radius: int = _px("u")
    feed_title_font: int = _px("font")
    feed_title_font_family: str = _px("family")
    feed_body_font: int = _px("font")
    feed_body_font_family: str = _px("family")
    feed_button_font: int = _px("font")
    feed_button_font_family: str = _px("family")
    feed_title_top: int = _px("y")
    feed_body_top: int = _px("y")
    feed_body_line_pitch: int = _px("y")
    feed_button_size: Size = _px("size")
    feed_button_bottom_margin: int = _px("y")
    wifi_pill_border_color: str = _px("color")
    feed_accent_color: str = _px("color")


@dataclass(frozen=True)
class Skin:
    """A complete per-resolution geometry set."""

    name: str = _px("const")
    size: Size = _px("const")  # the logical resolution this skin targets

    dashboard: DashboardSkin = _px("group")
    style: WidgetStyle = _px("group")
    header: HeaderSkin = _px("group")
    setup: SetupSkin = _px("group")
    keyboard: KeyboardSkin = _px("group")
    numpad: NumpadSkin = _px("group")
    overlays: OverlaySkin = _px("group")

    @property
    def width(self) -> int:
        return self.size[0]

    @property
    def height(self) -> int:
        return self.size[1]
