from __future__ import annotations

from ...colors import Color
from ...icons import Icon
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

    Placed inside a ListItem row at a native-px origin (the caller passes
    the skin's value column); the widget's internals stay authored in
    row-local design coordinates scaled with srect/spos. The 76px buttons
    are centered in the standard 80px row band. Posts BRIGHTNESS_UP/DOWN
    events; the owning state applies the change and calls set_percent()
    with the new value.
    """

    def __init__(self, x: float = 0, y: float = 0):
        super().__init__(round(x), round(y))

        button_font = load_font(size=76, family=FontFamily.PIXEL_TYPE)

        self.minus_button = Button(
            rect=srect(0, 2, 76, 76),
            text="-",
            icon=Icon.MINUS.glyph(),
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
            icon=Icon.PLUS.glyph(),
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
