"""Shared row builders for the settings-style list screens.

Setup and Software render the same row grid — icon cell, caption, control
column — from the active skin's ``setup`` group. These builders moved out
of SetupView when the Software screen was added so both screens stay
aligned and a skin restyles them together.
"""

from __future__ import annotations

from ..colors import Color
from ..skins import active_skin
from ..utils import FontFamily, load_font_px, su
from ..widgets.base.button import Button, ButtonEvents
from ..widgets.base.label import Label


def row_label(text: str) -> Label:
    """Standard row caption at row-local (label_x, label_dy)."""
    s = active_skin().setup
    return Label(
        text=text,
        font=load_font_px(s.row_font_size, FontFamily[s.row_font_family]),
        color=Color[s.row_text_color].rgb(),
        pos=(s.label_x, s.label_dy),
        center=False,
        bg_color=Color.BLACK.rgb(),
    )


def row_icon(glyph: str) -> Label:
    """Material-symbols row icon, centered in the icon cell at icon_x."""
    s = active_skin().setup
    return Label(
        text=glyph,
        font=load_font_px(s.icon_size, FontFamily.MATERIAL_SYMBOLS),
        color=Color[s.row_text_color].rgb(),
        pos=(s.icon_x, s.row_height // 2 + 4),
        center=True,
        bg_color=Color.BLACK.rgb(),
        antialias=True,
    )


def row_value(text: str) -> Label:
    """Plain, non-interactive value text in the control column, ellipsized
    to the column width — an uncontrolled string (dev versions, future
    fields) must not paint past the separator inset into the scrollbar."""
    skin = active_skin()
    s = skin.setup
    label = Label(
        text=text,
        font=load_font_px(s.row_font_size, FontFamily[s.row_font_family]),
        color=Color.WHITE.rgb(),
        pos=(s.value_x, s.label_dy),
        center=False,
        bg_color=Color.BLACK.rgb(),
    )
    available = skin.width - s.separator_inset - s.value_x
    raw = text
    while label.rect.width > available and len(raw) > 1:
        raw = raw[:-1]
        label.set_text(raw + "…")
    return label


def row_button(text: str, icon: str, events: ButtonEvents) -> Button:
    """Standard row action button, styled like a closed dropdown header:
    same rect (DROPDOWN_X to the row's right edge, stretched to touch
    the separator lines), text on the value_x column, the arrow icon in
    the chevron's spot, and the dropdown's pressed-grey glow instead of
    a border. Stops separator_clearance short of the separator lines so
    the pressed fill never covers them."""
    skin = active_skin()
    s = skin.setup
    width = skin.width - s.separator_inset - s.dropdown_x
    gap = s.row_pitch - s.row_height
    clearance = s.separator_clearance
    return Button(
        rect=(
            s.dropdown_x,
            # Integer cell math: round(-gap/2 + c) banker's-rounds a
            # half-pixel *upward* on odd gaps (800 skin: -17.5 -> -18),
            # lifting the control 1px onto the header line — which the
            # open dropdown's scrim then visibly blanks.
            clearance - gap // 2,
            width,
            s.row_height + gap - 2 * clearance,
        ),
        text=text,
        text_visible=True,
        font=load_font_px(s.row_font_size, FontFamily[s.row_font_family]),
        antialias=True,
        events=events,
        icon=icon,
        icon_size=s.chevron_icon_size,
        icon_font=load_font_px(
            s.chevron_icon_size, FontFamily.MATERIAL_SYMBOLS
        ),
        icon_offset_y=su(4),
        icon_position="right",
        icon_fixed_right=True,
        text_color=Color.WHITE.rgb(),
        content_align="left",
        padding=(
            s.value_x - s.dropdown_x,
            su(20),
            su(20),
            su(20),
        ),
        text_offset_y=su(4),
        show_border=False,
        pressed_gradient=(Color.DARKER_GREY.rgb(), Color.DARKER_GREY.rgb()),
    )
