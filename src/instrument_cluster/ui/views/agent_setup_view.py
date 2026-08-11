from pygame.sprite import LayeredDirty

from ...ui.colors import Color
from ...ui.events import (
    AGENT_BASIC_PRESSED,
    AGENT_BASIC_RELEASED,
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
)
from ...ui.skins import active_skin
from ...ui.utils import FontFamily, load_font, su
from ...ui.widgets.base.button import Button, ButtonEvents, ButtonGroup
from ...ui.widgets.base.label import Label
from .base import View
from .header import header_line, header_title


class AgentSetupView(View):
    """Pairing screen for a feed with a PC agent.

    The whole screen exists to communicate one URL, so that URL is the largest
    thing on it. Everything else — what the agent unlocks, the two steps, the
    status line — is support for the moment the user walks to their PC and
    types it in.
    """

    def __init__(self, feed_label: str = None, unlocks: str = None):
        self.ui_layer = LayeredDirty()
        self.background_color = Color.BLACK.rgb()

        self._w, self._h = active_skin().size
        self._feed_label = feed_label or "your game"
        self._unlocks = unlocks or "the remaining channels"

        self._init_ui_elements()

    def _init_ui_elements(self):
        self.title_label = header_title("Full telemetry setup")
        self.horizontal_line = header_line()

        info_font = load_font(size=44, family=FontFamily.PIXEL_TYPE)
        info_lines = [
            f"{self._unlocks} are not sent over the network by",
            f"{self._feed_label}. Reading them needs a small program",
            "running on the same PC as the game.",
            "",
            "On your gaming PC, open this address in a browser:",
        ]

        self.info_labels = []
        x = self._w // 8 - su(4)
        y = self._h // 4 - su(40)
        line_spacing = su(32)

        for line in info_lines:
            if line == "":
                y += line_spacing
                continue
            lbl = Label(
                text=line,
                font=info_font,
                color=Color.WHITE.rgb(),
                pos=(x, y),
                center=False,
            )
            self.info_labels.append(lbl)
            self.ui_layer.add(lbl)
            y += line_spacing

        # The one thing the user has to carry to another machine.
        self.url_label = Label(
            text="",
            font=load_font(size=72, family=FontFamily.NOTOSANS_REGULAR),
            color=Color.WHITE.rgb(),
            pos=(self._w // 2, self._h // 2 + su(40)),
            center=True,
            antialias=True,
        )

        status_font = load_font(size=44, family=FontFamily.PIXEL_TYPE)
        self.status_label = Label(
            text="Preparing download...",
            font=status_font,
            color=Color.LIGHT_GREEN.rgb(),
            pos=(self._w // 2, self._h // 2 + su(130)),
            center=True,
        )
        self.error_label = Label(
            text="",
            font=status_font,
            color=Color.LIGHT_RED.rgb(),
            pos=(self._w // 2, self._h // 2 + su(130)),
            center=True,
        )

        button_width = su(220)
        button_height = su(70)
        button_gap = su(60)
        total_width = button_width * 2 + button_gap
        start_x = (self._w - total_width) // 2
        btn_y = self._h // 2 + su(200)

        self.cancel_button = Button(
            rect=(start_x, btn_y, button_width, button_height),
            text="Cancel",
            text_visible=True,
            font=load_font(size=40, family=FontFamily.PIXEL_TYPE),
            antialias=True,
            events=ButtonEvents(
                pressed=BUTTON_BACK_PRESSED,
                released=BUTTON_BACK_RELEASED,
            ),
        )
        # The escape hatch: the network-only feed still works, it just leaves
        # some gauges inactive. Nobody should be stuck on this screen because
        # they cannot get to their PC right now.
        self.basic_button = Button(
            rect=(
                start_x + button_width + button_gap,
                btn_y,
                button_width,
                button_height,
            ),
            text="Basic setup",
            text_visible=True,
            font=load_font(size=40, family=FontFamily.PIXEL_TYPE),
            antialias=True,
            events=ButtonEvents(
                pressed=AGENT_BASIC_PRESSED,
                released=AGENT_BASIC_RELEASED,
            ),
        )

        self.btns = ButtonGroup()
        self.btns.add(self.basic_button, self.cancel_button)

        self.ui_layer.add(
            self.title_label,
            self.url_label,
            self.status_label,
            self.error_label,
            *self.btns.sprites(),
        )

    def set_url(self, url: str):
        self.url_label.set_text(url)

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
