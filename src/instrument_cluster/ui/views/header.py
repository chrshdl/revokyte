"""The title + back-button header shared by the full-screen setup views.

Every non-dashboard view (Setup, Wi-Fi, EnterIP, Install, extension setup)
carries the same chrome: a title at the top-left, an icon button in the
top-right corner, and the horizontal rule under both. This module builds
them from the active skin's ``header`` group so the views never each carry
the geometry — and so a skin restyles all of them at once.
"""

from __future__ import annotations

from ..colors import Color
from ..skins import active_skin
from ..utils import FontFamily, load_font_px
from ..widgets.base.button import Button, ButtonEvents
from ..widgets.base.label import Label
from ..widgets.base.line import Line


def header_title(text: str) -> Label:
    hd = active_skin().header
    return Label(
        text=text,
        font=load_font_px(
            hd.title_font_size, FontFamily[hd.title_font_family]
        ),
        color=Color[hd.title_color].rgb(),
        pos=hd.title_topleft,
        center=False,
    )


def header_line() -> Line:
    skin = active_skin()
    return Line(
        start_pos=(0, skin.header.line_y),
        length=skin.width,
        color=Color[skin.header.line_color].rgb(),
    )


def corner_button_rect() -> tuple[int, int, int, int]:
    """The top-right corner button slot (back / skip)."""
    skin = active_skin()
    hd = skin.header
    w, h = hd.back_button_size
    return (skin.width - w - hd.back_button_gap, hd.back_button_y, w, h)


def corner_button(icon: str, events: ButtonEvents) -> Button:
    """An icon-only button in the corner slot (back arrow, close, skip)."""
    hd = active_skin().header
    return Button(
        rect=corner_button_rect(),
        text="x",
        text_visible=False,
        events=events,
        font=load_font_px(hd.title_font_size, FontFamily.NOTOSANS_REGULAR),
        antialias=True,
        icon=icon,
        icon_color=Color.WHITE.rgb(),
        icon_size=hd.back_button_icon,
        icon_font=load_font_px(hd.back_button_icon, FontFamily.MATERIAL_SYMBOLS),
        icon_position="center",
    )
