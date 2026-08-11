"""Field ↔ canvas bindings: where a skin field lands on screen, per view.

A Binding gives a skin field a hit-target and a manipulation style on the
canvas. ``rect_fn(skin)`` recomputes the target from current skin values
every frame, so bindings can never go stale; anchors tell the canvas how a
drag maps back onto the stored value. Approximate-but-honest: fields whose
layout math lives deep in view code (individual keyboard keys, row
internals) stay coarse or unbound — the rendered surface is the ground
truth, bindings are only handles. Unbound fields are edited via the tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pygame

RECT = "rect"  # move + resize; value is (x, y, w, h)
POINT = "point"  # move only; value is (x, y)
HLINE = "hline"  # vertical drag edits a single y value
VLINE = "vline"  # horizontal drag edits a single x value


@dataclass(frozen=True)
class Binding:
    path: str
    kind: str
    rect_fn: Callable[[object], pygame.Rect]
    #: "topleft" | "center" — how the stored rect anchors on screen.
    anchor: str = "topleft"
    #: extra note shown in the status bar (e.g. "pre-shift column").
    note: str = ""


def _r(x, y, w, h) -> pygame.Rect:
    return pygame.Rect(round(x), round(y), round(w), round(h))


def _centered(rect) -> pygame.Rect:
    x, y, w, h = rect
    return _r(x - w // 2, y - h // 2, w, h)


def _point_rect(pos, pad=14) -> pygame.Rect:
    return _r(pos[0] - pad, pos[1] - pad, 2 * pad, 2 * pad)


def _hline_rect(skin, y, pad=6) -> pygame.Rect:
    return _r(0, y - pad, skin.width, 2 * pad)


def _vline_rect(skin, x, pad=6) -> pygame.Rect:
    return _r(x - pad, 0, 2 * pad, skin.height)


def _dashboard(lights: bool) -> list[Binding]:
    d = "dashboard."
    note = "pre-shift column" if lights else ""
    out = [
        Binding(d + "gear_rect", RECT, lambda s: _centered(s.dashboard.gear_rect), "center"),
        Binding(d + "speed_rect", RECT, lambda s: _centered(s.dashboard.speed_rect), "center"),
        Binding(d + "rpm_rect", RECT, lambda s: _centered(s.dashboard.rpm_rect), "center"),
        Binding(d + "delta_rect", RECT, lambda s: _centered(s.dashboard.delta_rect), "center", note),
        Binding(d + "lap_time_rect", RECT, lambda s: _centered(s.dashboard.lap_time_rect), "center", note),
        Binding(d + "fastest_lap_rect", RECT, lambda s: _centered(s.dashboard.fastest_lap_rect), "center", note),
        Binding(d + "predicted_lap_rect", RECT, lambda s: _centered(s.dashboard.predicted_lap_rect), "center", note),
        Binding(d + "fuel_per_lap_rect", RECT, lambda s: _centered(s.dashboard.fuel_per_lap_rect), "center", note),
        Binding(d + "fuel_laps_rect", RECT, lambda s: _centered(s.dashboard.fuel_laps_rect), "center", note),
        Binding(d + "track_rect", RECT, lambda s: _centered(s.dashboard.track_rect), "center", note),
        Binding(d + "lap_counter_rect", RECT, lambda s: _r(*s.dashboard.lap_counter_rect), "topleft", note),
        Binding(
            d + "tire_grid.origin",
            POINT,
            lambda s: _r(
                s.dashboard.tire_grid.origin[0],
                s.dashboard.tire_grid.origin[1],
                s.dashboard.tire_grid.cell[0],
                s.dashboard.tire_grid.cell[1],
            ),
            "topleft",
            "top-left tire cell",
        ),
        Binding(d + "slot_dots.center", POINT, lambda s: _point_rect(s.dashboard.slot_dots.center)),
        Binding(d + "footer_y", HLINE, lambda s: _hline_rect(s, s.dashboard.footer_y)),
    ]
    if lights:
        out.append(
            Binding(
                d + "status_light_rect",
                RECT,
                lambda s: _r(*s.dashboard.status_light_rect),
                "topleft",
                "left strip; right is mirrored",
            )
        )
    return out


def _setup_grid() -> list[Binding]:
    s_ = "setup."

    def row0(s):
        return _r(0, s.setup.row_top, s.width, s.setup.row_height)

    return [
        Binding(s_ + "row_top", HLINE, lambda s: _hline_rect(s, s.setup.row_top)),
        Binding(
            s_ + "row_height",
            RECT,
            row0,
            "topleft",
            "first row band (resize bottom edge)",
        ),
        Binding(s_ + "icon_x", VLINE, lambda s: _vline_rect(s, s.setup.icon_x)),
        Binding(s_ + "label_x", VLINE, lambda s: _vline_rect(s, s.setup.label_x)),
    ]


def _setup() -> list[Binding]:
    s_ = "setup."
    return (
        _setup_grid()
        + [
            Binding(s_ + "value_x", VLINE, lambda s: _vline_rect(s, s.setup.value_x)),
            Binding(
                s_ + "dropdown_x", VLINE, lambda s: _vline_rect(s, s.setup.dropdown_x)
            ),
        ]
        + _header()
    )


def _header() -> list[Binding]:
    h = "header."

    def back_rect(s):
        w, hh = s.header.back_button_size
        return _r(s.width - w - s.header.back_button_gap, s.header.back_button_y, w, hh)

    return [
        Binding(h + "title_topleft", POINT, lambda s: _point_rect(s.header.title_topleft, 22)),
        Binding(h + "line_y", HLINE, lambda s: _hline_rect(s, s.header.line_y)),
        Binding(
            h + "back_button_size",
            RECT,
            back_rect,
            "topleft",
            "position derives from size + gap + y",
        ),
    ]


def _keyboard() -> list[Binding]:
    k = "keyboard."

    def board(s):
        kb = s.keyboard
        w = 10 * kb.key_w + 9 * kb.gap
        h = 3 * kb.row_step + kb.key_h
        return _r((s.width - w) / 2, kb.top, w, h)

    def pw_row(s):
        kb = s.keyboard
        kb_left = (s.width - (10 * kb.key_w + 9 * kb.gap)) / 2
        return _r(kb_left, kb.pw_row_y, s.width - 2 * kb_left, kb.pw_row_h)

    return [
        Binding(k + "top", HLINE, lambda s: _hline_rect(s, s.keyboard.top), note="keyboard top"),
        Binding(k + "pw_row_y", RECT, pw_row, "topleft", "password row (y/h editable)"),
    ] + _header()


def _wifi_manual() -> list[Binding]:
    k = "keyboard."
    return [
        Binding(k + "manual_field_rect", RECT, lambda s: _r(*s.keyboard.manual_field_rect)),
        Binding(k + "manual_ssid_label_pos", POINT, lambda s: _point_rect(s.keyboard.manual_ssid_label_pos, 18)),
        Binding(k + "manual_pw_label_pos", POINT, lambda s: _point_rect(s.keyboard.manual_pw_label_pos, 18)),
    ] + _keyboard()


def _numpad() -> list[Binding]:
    n = "numpad."

    def grid(s):
        np = s.numpad
        cols = np.buttons_per_row
        rows = 4  # 12 keys / 3 per row
        w = cols * np.button_dims[0] + (cols - 1) * np.button_margin
        h = rows * np.button_dims[1] + (rows - 1) * np.button_margin
        return _r(np.offset[0], np.offset[1], w, h)

    return [
        Binding(n + "field_rect", RECT, lambda s: _r(*s.numpad.field_rect)),
        Binding(n + "del_rect", RECT, lambda s: _r(*s.numpad.del_rect)),
        Binding(n + "ok_rect", RECT, lambda s: _r(*s.numpad.ok_rect)),
        Binding(n + "offset", POINT, grid, "topleft", "numpad grid origin"),
        Binding(n + "recent_offset", POINT, lambda s: _point_rect(s.numpad.recent_offset, 20)),
        Binding(n + "recent_position", POINT, lambda s: _point_rect(s.numpad.recent_position, 20)),
    ] + _header()


def _overlays() -> list[Binding]:
    o = "overlays."

    def card(s):
        w, h = s.overlays.feed_card_size
        return _r((s.width - w) // 2, (s.height - h) // 2, w, h)

    return [
        Binding(o + "no_signal_rect", RECT, lambda s: _r(*s.overlays.no_signal_rect)),
        Binding(o + "wifi_pill_center_y", HLINE, lambda s: _hline_rect(s, s.overlays.wifi_pill_center_y)),
        Binding(o + "feed_card_size", RECT, card, "topleft", "centred; only size editable"),
    ]


def bindings_for(view_id: str) -> list[Binding]:
    if view_id == "dashboard":
        return _dashboard(lights=False)
    if view_id == "dashboard_lights":
        return _dashboard(lights=True)
    if view_id == "overlays":
        # The dashboard underneath is context, not the editable subject —
        # matching the view's widget tree.
        return _overlays()
    if view_id == "setup":
        return _setup()
    if view_id in ("wifi_scan",):
        # The network list rides the setup grid; no controls column here.
        return _setup_grid() + _header()
    if view_id == "wifi_password":
        return _keyboard()
    if view_id == "wifi_manual":
        return _wifi_manual()
    if view_id == "enter_ip":
        return _numpad()
    if view_id in ("install", "agent"):
        return _header()
    return []
