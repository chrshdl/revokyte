"""Accel-run logger view: instructions plus live capture status.

Everything interactive lives in AccelLogState; this view renders the
recorder's state. Left column: how to drive a clean full-throttle pull.
Right column: what the recorder sees right now (car, gear, rpm, pedal),
the capture state, the last run's verdict, and how many runs are already
on disk for this car.
"""

from pygame.sprite import LayeredDirty

from ...ui.colors import Color
from ...ui.constants import (
    HEADER_BACKBUTTON_POSITION,
    HEADER_BACKBUTTON_SIZE,
    HEADER_TITLE_FONT_SIZE,
    HEADER_TITLE_TOPLEFT,
)
from ...ui.events import BUTTON_BACK_PRESSED, BUTTON_BACK_RELEASED
from ...ui.utils import FontFamily, load_font, spos, srect
from ...ui.widgets.base.button import Button, ButtonEvents
from ...ui.widgets.base.label import Label
from ...ui.widgets.base.line import Line
from .base import View

_DIM = (150, 150, 150)
_AMBER = (255, 180, 40)

_INSTRUCTIONS = (
    "Log a few clean full-throttle pulls; they",
    "measure this car's real torque curve and",
    "help improve the engine model.",
    "",
    "1.  Pick a long, flat straight",
    "     (Special Stage Route X works well).",
    "2.  Use 2nd or 3rd gear, revs settled low.",
    "3.  Floor it and hold to the rev limiter.",
    "     TC off, wheel straight, no wheelspin.",
    "4.  Lift, slow, repeat - three clean pulls.",
    "",
    "Runs save automatically. A pull counts",
    "when it exceeds 1.5 s and 1500 rpm.",
)

_LEFT_X = 40
_RIGHT_X = 720
_TOP_Y = 120
_LINE_H = 40
_STATUS_FONT = 30
_RESULT_FONT = 26
_VALUE_FONT = 44


class AccelLogView(View):
    def __init__(self, save_dir: str):
        self.ui_layer = LayeredDirty()
        self.ui_layer._use_update = True

        self.title_label = Label(
            text="Accel run logger",
            font=load_font(
                size=HEADER_TITLE_FONT_SIZE, family=FontFamily.NOTOSANS_LIGHT
            ),
            color=Color.WHITE.rgb(),
            pos=spos(*HEADER_TITLE_TOPLEFT),
            center=False,
        )
        self.back_button = Button(
            rect=srect(*HEADER_BACKBUTTON_POSITION, *HEADER_BACKBUTTON_SIZE),
            text="x",
            text_color=Color.WHITE.rgb(),
            text_visible=False,
            events=ButtonEvents(
                pressed=BUTTON_BACK_PRESSED,
                released=BUTTON_BACK_RELEASED,
            ),
            font=load_font(size=50, family=FontFamily.NOTOSANS_REGULAR),
            antialias=True,
            icon="",
            icon_color=Color.WHITE.rgb(),
            icon_size=54,
            icon_position="center",
        )
        self.horizontal_line = Line()
        self.ui_layer.add(self.title_label, self.back_button)

        font_body = load_font(size=28, family=FontFamily.NOTOSANS_REGULAR)
        for i, line in enumerate(_INSTRUCTIONS):
            if not line:
                continue
            self.ui_layer.add(
                Label(
                    text=line,
                    font=font_body,
                    color=Color.WHITE.rgb() if not line.startswith(" ") else _DIM,
                    pos=spos(_LEFT_X, _TOP_Y + i * _LINE_H),
                    center=False,
                    bg_color=Color.BLACK.rgb(),
                )
            )

        font_status = load_font(size=_STATUS_FONT, family=FontFamily.NOTOSANS_REGULAR)
        font_result = load_font(size=_RESULT_FONT, family=FontFamily.NOTOSANS_REGULAR)
        font_value = load_font(size=_VALUE_FONT, family=FontFamily.PIXEL_TYPE)

        def status_label(row: int, text: str = "", color=Color.WHITE.rgb(), font=None):
            label = Label(
                text=text,
                font=font or font_status,
                color=color,
                pos=spos(_RIGHT_X, _TOP_Y + row * (_LINE_H + 14)),
                center=False,
                bg_color=Color.BLACK.rgb(),
            )
            self.ui_layer.add(label)
            return label

        self.car_label = status_label(0, "no live car", _DIM)
        self.state_label = status_label(1, "WAITING FOR TELEMETRY", _AMBER, font_value)
        self.live_label = status_label(2, "", Color.WHITE.rgb(), font_value)
        self.result_label = status_label(3, "", _DIM, font_result)
        self.runs_label = status_label(4, "", Color.WHITE.rgb())

        # Where the files land — small print at the bottom.
        self.ui_layer.add(
            Label(
                text=f"runs saved to {save_dir}",
                font=load_font(size=22, family=FontFamily.NOTOSANS_REGULAR),
                color=_DIM,
                pos=spos(_LEFT_X, 668),
                center=False,
                bg_color=Color.BLACK.rgb(),
            )
        )

        self.background_color = Color.BLACK.rgb()

    # -- state-facing setters ------------------------------------------------

    def set_car(self, text: str, live: bool) -> None:
        self.car_label.set_text(text)
        self.car_label.color = Color.WHITE.rgb() if live else _DIM

    def set_capture_state(self, text: str, color) -> None:
        self.state_label.color = color
        self.state_label.set_text(text)

    def set_live(self, gear: int, rpm: float, throttle: float) -> None:
        # Coarse rounding keeps the label from going dirty on every frame.
        self.live_label.set_text(
            f"gear {gear}   {int(rpm // 50) * 50:>5} rpm   {int(throttle * 100):>3}%"
        )

    def set_result(self, text: str, good: bool) -> None:
        self.result_label.color = Color.GREEN.rgb() if good else Color.LIGHT_RED.rgb()
        self.result_label.set_text(text)

    def set_runs(self, count: int) -> None:
        self.runs_label.set_text(f"runs on disk for this car: {count}")

    # -- View contract -------------------------------------------------------

    def draw_static_elements(self, background_surface):
        self.horizontal_line.draw(background_surface)

    def update(self, dt: float):
        self.ui_layer.update(dt)

    def draw(self, surface, background):
        self.ui_layer.clear(surface, background)
        return self.ui_layer.draw(surface)

    def full_paint(self, surface, background):
        if background:
            surface.blit(background, (0, 0))
        for sprite in self.ui_layer.sprites():
            sprite.dirty = 1
        self.ui_layer.clear(surface, background)
        self.ui_layer.draw(surface)

    def handle_event(self, event) -> bool:
        self.back_button.handle_event(event)
        return False
