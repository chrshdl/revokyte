from __future__ import annotations

from ...colors import Color
from ...events import (
    BRIGHTNESS_DOWN_PRESSED,
    BRIGHTNESS_DOWN_RELEASED,
    BRIGHTNESS_UP_PRESSED,
    BRIGHTNESS_UP_RELEASED,
)
from ...utils import FontFamily, load_font, spos, srect
from ..base.button import Button, ButtonEvents
from ..base.container import Container
from ..base.label import Label


class BrightnessWidget(Container):
    """Backlight brightness control: a -/+ stepper with a percent readout.

    Authored in local design coordinates so it can be placed inside a
    ListItem row; the 76px buttons are centered in the standard 80px row
    band. Posts BRIGHTNESS_UP/DOWN events; the owning state applies
    the change and calls set_percent() with the new value.
    """

    def __init__(self, x: float = 0, y: float = 0):
        super().__init__(*spos(x, y))

        button_font = load_font(size=76, family=FontFamily.PIXEL_TYPE)

        self.minus_button = Button(
            rect=srect(0, 2, 76, 76),
            text="-",
            icon="\ue15b",
            icon_size=50,
            icon_position="center",
            text_visible=False,
            events=ButtonEvents(
                pressed=BRIGHTNESS_DOWN_PRESSED,
                released=BRIGHTNESS_DOWN_RELEASED,
            ),
            font=button_font,
            text_color=Color.WHITE.rgb(),
            antialias=True,
        )
        self.percent_label = Label(
            text="-- %",
            font=load_font(size=32, family=FontFamily.NOTOSANS_LIGHT),
            color=Color.WHITE.rgb(),
            pos=spos(255, 42),
            center=True,
            antialias=True,
        )
        self.plus_button = Button(
            rect=srect(434, 2, 76, 76),
            text="+",
            icon="\ue145",
            icon_size=50,
            icon_position="center",
            text_visible=False,
            events=ButtonEvents(
                pressed=BRIGHTNESS_UP_PRESSED,
                released=BRIGHTNESS_UP_RELEASED,
            ),
            font=button_font,
            text_color=Color.WHITE.rgb(),
            antialias=True,
        )

        self.add(self.minus_button, self.percent_label, self.plus_button)

    def set_percent(self, value: int) -> None:
        self.percent_label.set_text(f"{value} %")
