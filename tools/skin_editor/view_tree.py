"""Per-view widget trees: which skin fields the designer sees per view.

Selecting a view scopes the left tree to the widgets that view actually
renders — EB GUIDE-style: sections are the view's widgets, leaves are the
skin fields that style them. A field may appear under several views (the
header block styles every setup screen), but every editable field must
appear in at least one view — ``test_skin_editor_view_tree.py`` walks the
schema and fails when a newly added field is left unassigned.

Only ``name`` and ``size`` are deliberately absent: they are the skin's
identity, not design knobs.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shared section blocks
# ---------------------------------------------------------------------------

_HEADER = [
    (
        "Header",
        [
            "header.title_topleft",
            "header.title_font_size",
            "header.title_font_family",
            "header.line_y",
        ],
    ),
    (
        "Back button",
        [
            "header.back_button_size",
            "header.back_button_y",
            "header.back_button_gap",
            "header.back_button_icon",
        ],
    ),
]

_WIDGET_FRAME = [
    (
        "Widget frame (all gauges)",
        [
            "style.header_font_size",
            "style.header_font_family",
            "style.header_margin",
            "style.value_offset_y",
            "style.border_width",
            "style.border_radius",
            "style.digit_gap",
        ],
    ),
]

_DASHBOARD_CORE = [
    ("Gear", ["dashboard.gear_rect", "dashboard.fonts.gear", "dashboard.fonts.gear_family"]),
    ("Speed", ["dashboard.speed_rect", "dashboard.fonts.speed", "dashboard.fonts.speed_family"]),
    (
        "RPM bar",
        [
            "dashboard.rpm_rect",
            "dashboard.fonts.rpm_label",
            "dashboard.fonts.rpm_label_family",
            "style.rpm.padding_x",
            "style.rpm.padding_y",
            "style.rpm.tick_major_len",
            "style.rpm.tick_minor_len",
            "style.rpm.tick_major_w",
            "style.rpm.tick_minor_w",
            "style.rpm.label_gap",
        ],
    ),
    (
        "Delta (Time Diff)",
        [
            "dashboard.delta_rect",
            "dashboard.fonts.delta",
            "dashboard.fonts.delta_family",
            "dashboard.fonts.delta_state",
            "dashboard.fonts.delta_state_family",
            "style.delta.seg_width",
            "style.delta.seg_height",
            "style.delta.seg_gap",
            "style.delta.seg_slant",
            "style.delta.seg_y_offset",
            "style.delta.value_offset_y",
            "style.delta.state_offset_y",
        ],
    ),
    (
        "Tire temps",
        [
            "dashboard.tire_grid.origin",
            "dashboard.tire_grid.cell",
            "dashboard.tire_grid.col_step",
            "dashboard.tire_grid.row_step",
            "dashboard.fonts.tire",
            "dashboard.fonts.tire_family",
        ],
    ),
    ("Fastest lap", [
            "dashboard.fastest_lap_rect",
            "dashboard.fonts.fastest_lap",
            "dashboard.fonts.fastest_lap_family",
        ]),
    (
        "Predicted lap",
        [
            "dashboard.predicted_lap_rect",
            "dashboard.fonts.predicted_lap",
            "dashboard.fonts.predicted_lap_family",
        ],
    ),
    ("Previous lap", [
            "dashboard.lap_time_rect",
            "dashboard.fonts.lap_time",
            "dashboard.fonts.lap_time_family",
        ]),
    ("Lap counter", [
            "dashboard.lap_counter_rect",
            "dashboard.fonts.lap_counter",
            "dashboard.fonts.lap_counter_family",
        ]),
    ("Track name", [
            "dashboard.track_rect",
            "dashboard.fonts.track",
            "dashboard.fonts.track_family",
        ]),
    (
        "Fuel pair",
        [
            "dashboard.fuel_per_lap_rect",
            "dashboard.fuel_laps_rect",
            "dashboard.fonts.fuel",
            "dashboard.fonts.fuel_family",
        ],
    ),
    (
        "Footer / Setup button",
        [
            "dashboard.footer_y",
            "dashboard.button_h",
            "dashboard.setup_button_w",
            "dashboard.setup_button_font",
            "dashboard.setup_button_font_family",
            "dashboard.setup_button_icon",
            "dashboard.setup_button_pad_top",
        ],
    ),
    (
        "Slot name & dots",
        [
            "dashboard.slot_name_left_inset",
            "dashboard.fonts.slot_name",
            "dashboard.fonts.slot_name_family",
            "dashboard.slot_dots.center",
            "dashboard.slot_dots.radius",
            "dashboard.slot_dots.pitch",
        ],
    ),
    ("Page swipe", ["dashboard.swipe_min_dx", "dashboard.swipe_max_dy"]),
] + _WIDGET_FRAME

_STATUS_LIGHTS = [
    (
        "Status-light strips",
        [
            "dashboard.status_light_rect",
            "dashboard.status_light_dot_spacing",
            "dashboard.status_light_dot_radius",
            "dashboard.status_strip_w",
            "dashboard.shift_l_on",
            "dashboard.shift_r_on",
        ],
    ),
]

_SETUP_GRID = [
    (
        "Row grid",
        ["setup.row_top", "setup.row_pitch", "setup.row_height"],
    ),
    (
        "Row content",
        [
            "setup.row_font_size",
            "setup.row_font_family",
            "setup.icon_x",
            "setup.icon_size",
            "setup.label_x",
            "setup.label_dy",
        ],
    ),
    (
        "Separators",
        [
            "setup.separator_inset",
            "setup.separator_width",
            "setup.separator_clearance",
        ],
    ),
    (
        "Scrollbar",
        [
            "style.scrollbar.track_width",
            "style.scrollbar.track_margin_right",
            "style.scrollbar.min_thumb_height",
            "style.scrollbar.track_hit_pad",
            "style.scrollbar.drag_threshold",
        ],
    ),
]

_KEYBOARD = [
    (
        "Keyboard",
        [
            "keyboard.key_w",
            "keyboard.key_h",
            "keyboard.gap",
            "keyboard.top",
            "keyboard.row_step",
            "keyboard.special_w",
            "keyboard.space_w",
            "keyboard.key_font",
            "keyboard.key_font_family",
            "keyboard.small_font",
            "keyboard.small_font_family",
        ],
    ),
    (
        "Password row",
        [
            "keyboard.pw_row_y",
            "keyboard.pw_row_h",
            "keyboard.pw_font",
            "keyboard.pw_font_family",
        ],
    ),
]

# ---------------------------------------------------------------------------
# The per-view trees
# ---------------------------------------------------------------------------

VIEW_TREES: dict[str, list[tuple[str, list[str]]]] = {
    "dashboard": _DASHBOARD_CORE,
    "dashboard_lights": _STATUS_LIGHTS + _DASHBOARD_CORE,
    "overlays": [
        (
            "NO SIGNAL banner",
            [
            "overlays.no_signal_rect",
            "overlays.no_signal_font",
            "overlays.no_signal_font_family",
        ],
        ),
        (
            "Wi-Fi pill",
            [
                "overlays.wifi_pill_height",
                "overlays.wifi_pill_center_y",
                "overlays.wifi_pill_pad_x",
                "overlays.wifi_pill_font",
            "overlays.wifi_pill_font_family",
            ],
        ),
        (
            "Feed-update card",
            [
                "overlays.feed_card_size",
                "overlays.feed_card_radius",
                "overlays.feed_title_font",
            "overlays.feed_title_font_family",
                "overlays.feed_body_font",
            "overlays.feed_body_font_family",
                "overlays.feed_title_top",
                "overlays.feed_body_top",
                "overlays.feed_body_line_pitch",
                "overlays.feed_button_size",
                "overlays.feed_button_font",
            "overlays.feed_button_font_family",
                "overlays.feed_button_bottom_margin",
            ],
        ),
    ],
    "setup": _HEADER
    + _SETUP_GRID
    + [
        (
            "Controls column",
            ["setup.value_x", "setup.dropdown_x", "setup.chevron_icon_size"],
        ),
        (
            "Toggle pill",
            [
                "style.toggle.track_w",
                "style.toggle.track_h",
                "style.toggle.knob_margin",
            ],
        ),
    ],
    "wifi_scan": _HEADER
    + [
        (
            "Scan button",
            ["keyboard.rescan_size", "keyboard.rescan_font", "keyboard.rescan_font_family"],
        ),
        (
            "Network list",
            ["setup.visible_network_cells"],
        ),
    ]
    + _SETUP_GRID,
    "wifi_password": _HEADER + _KEYBOARD,
    "wifi_manual": _HEADER
    + [
        (
            "Manual-entry form",
            [
                "keyboard.manual_label_font",
            "keyboard.manual_label_font_family",
                "keyboard.manual_field_font",
            "keyboard.manual_field_font_family",
                "keyboard.manual_ssid_label_pos",
                "keyboard.manual_pw_label_pos",
                "keyboard.manual_field_rect",
                "keyboard.manual_pw_left",
            ],
        ),
    ]
    + _KEYBOARD,
    "enter_ip": _HEADER
    + [
        (
            "IP field",
            ["numpad.field_rect", "numpad.field_font",
            "numpad.field_font_family", "numpad.del_rect"],
        ),
        (
            "Numpad",
            [
                "numpad.buttons_per_row",
                "numpad.button_dims",
                "numpad.button_margin",
                "numpad.offset",
                "numpad.key_font",
            "numpad.key_font_family",
                "numpad.ok_rect",
            ],
        ),
        (
            "Recent connections",
            [
                "numpad.recent_position",
                "numpad.recent_label_font",
            "numpad.recent_label_font_family",
                "numpad.recent_per_row",
                "numpad.recent_dims",
                "numpad.recent_margin",
                "numpad.recent_offset",
            ],
        ),
    ],
    "install": _HEADER,
    "agent": _HEADER,
}


def tree_for(view_id: str) -> list[tuple[str, list[str]]]:
    return VIEW_TREES.get(view_id, [])


def all_assigned_paths() -> set[str]:
    return {
        path
        for sections in VIEW_TREES.values()
        for _label, paths in sections
        for path in paths
    }
