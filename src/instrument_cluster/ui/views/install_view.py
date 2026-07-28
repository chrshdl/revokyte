from pygame.sprite import LayeredDirty

from ...peripherals.display import DESIGN_HEIGHT, DESIGN_WIDTH
from ...ui.colors import Color
from ...ui.constants import HEADER_TITLE_FONT_SIZE, HEADER_TITLE_TOPLEFT
from ...ui.events import (
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
    INSTALL_PRESSED,
    INSTALL_RELEASED,
)
from ...ui.utils import FontFamily, load_font, spos, srect
from ...ui.widgets.base.button import Button, ButtonEvents, ButtonGroup
from ...ui.widgets.base.label import Label
from ...ui.widgets.base.line import Line
from .base import View


class InstallView(View):
    def __init__(self, feed_label: str = None, updating: bool = False):
        self.ui_layer = LayeredDirty()
        self.background_color = Color.BLACK.rgb()

        self._w, self._h = DESIGN_WIDTH, DESIGN_HEIGHT
        self._feed_label = feed_label or "your game"
        self._updating = updating

        self._init_ui_elements()

    def _init_ui_elements(self):
        self.title_label = Label(
            text=(
                "Updating UDP Telemetry"
                if self._updating
                else "Install UDP Telemetry?"
            ),
            font=load_font(
                size=HEADER_TITLE_FONT_SIZE, family=FontFamily.NOTOSANS_LIGHT
            ),
            color=Color.WHITE.rgb(),
            pos=spos(*HEADER_TITLE_TOPLEFT),
            center=False,
        )
        self.horizontal_line = Line()

        info_font = load_font(size=44, family=FontFamily.PIXEL_TYPE)
        info_lines = [
            "You are about to download and install telemetry software",
            f"enabling this device to receive data from {self._feed_label}.",
            "",
            "This telemetry software is independently developed and",
            "maintained and is not affiliated with or endorsed by the",
            "respective game's publisher.",
            "",
            (
                "Updating now. Press Cancel to go back."
                if self._updating
                else "Press Install to proceed or Cancel to go back."
            ),
        ]

        self.info_labels = []
        x = self._w // 8 - 4
        y = self._h // 4 - 16
        line_spacing = 32

        for line in info_lines:
            if line == "":
                y += line_spacing
                continue
            lbl = Label(
                text=line,
                font=info_font,
                color=Color.WHITE.rgb(),
                pos=spos(x, y),
                center=False,
            )
            self.info_labels.append(lbl)
            self.ui_layer.add(lbl)
            y += line_spacing

        status_font = load_font(size=44, family=FontFamily.PIXEL_TYPE)

        self.status_label = Label(
            text="",
            font=status_font,
            color=Color.LIGHT_GREEN.rgb(),
            pos=spos(self._w // 2, self._h // 2 + 130),
            center=True,
        )

        self.error_label = Label(
            text="",
            font=status_font,
            color=Color.LIGHT_RED.rgb(),
            pos=spos(self._w // 2, self._h // 2 + 130),
            center=True,
        )

        button_width = 220
        button_height = 70
        button_gap = 60
        # An update starts on its own, so Install would be a dead control on
        # a screen that is already installing — Cancel alone, centred.
        buttons = 1 if self._updating else 2
        total_width = button_width * buttons + button_gap * (buttons - 1)
        start_x = (self._w - total_width) // 2
        btn_y = self._h // 2 + 200

        self.cancel_button = Button(
            rect=srect(start_x, btn_y, button_width, button_height),
            text="Cancel",
            text_visible=True,
            font=load_font(size=40, family=FontFamily.PIXEL_TYPE),
            antialias=True,
            events=ButtonEvents(
                pressed=BUTTON_BACK_PRESSED,
                released=BUTTON_BACK_RELEASED,
            ),
        )

        self.install_button = Button(
            rect=srect(
                start_x + button_width + button_gap,
                btn_y,
                button_width,
                button_height,
            ),
            text="Install",
            text_visible=True,
            font=load_font(size=40, family=FontFamily.PIXEL_TYPE),
            antialias=True,
            events=ButtonEvents(
                pressed=INSTALL_PRESSED,
                released=INSTALL_RELEASED,
            ),
        )

        self.btns = ButtonGroup()
        if self._updating:
            self.btns.add(self.cancel_button)
        else:
            self.btns.add(self.install_button, self.cancel_button)

        self.ui_layer.add(
            self.title_label, self.status_label, self.error_label, *self.btns.sprites()
        )

    def set_status(self, text: str):
        self.status_label.set_text(text)
        if text:
            self.error_label.set_text("")

    def set_error(self, text: str):
        self.error_label.set_text(text)
        if text:
            self.status_label.set_text("")

    def draw_static_elements(self, background_surface):
        self.horizontal_line.draw(background_surface)

    def update(self, dt):
        self.ui_layer.update(dt)

    def draw(self, surface, background):
        self.ui_layer.clear(surface, background)
        return self.ui_layer.draw(surface)

    def full_paint(self, surface, background):
        if background:
            self.draw_static_elements(background)
            surface.blit(background, (0, 0))

        for sprite in self.ui_layer.sprites():
            sprite.dirty = 1

        self.ui_layer.clear(surface, background)
        self.ui_layer.draw(surface)

    def handle_event(self, event) -> bool:
        self.btns.handle_event(event)
        return False
