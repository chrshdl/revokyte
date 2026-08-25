from dataclasses import dataclass
from pygame.sprite import LayeredDirty

from ...ui.colors import Color
from ...ui.events import (
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
    LISTENER_CONTINUE_PRESSED,
    LISTENER_CONTINUE_RELEASED,
)
from ...ui.skins import active_skin
from ...ui.utils import FontFamily, load_font, su
from ...ui.widgets.base.button import Button, ButtonEvents, ButtonGroup
from ...ui.widgets.base.label import Label
from .base import View
from .header import header_line, header_title


@dataclass(frozen=True)
class ListenerSetupContext:
    """What ListenerSetupView rebinds on every entry (was its ctor args)."""

    feed_label: str | None = None


class ListenerSetupView(View):
    """Setup screen for a feed that pushes telemetry to an address we show.

    Mirrors AgentSetupView's shape: the whole screen exists to communicate
    one piece of information, so that information — here, this device's own
    address and port — is the largest thing on it.
    """

    def __init__(self, feed_label: str = None):
        self.ui_layer = LayeredDirty()
        self.background_color = Color.BLACK.rgb()

        self._w, self._h = active_skin().size
        self._feed_label = feed_label or "your game"

        self._init_ui_elements()

    def _init_ui_elements(self):
        self.title_label = header_title("Telemetry setup")
        self.horizontal_line = header_line()

        info_font = load_font(size=44, family=FontFamily.PIXEL_TYPE)
        info_lines = self._info_lines()

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

        # The one thing the user has to carry to the game's settings.
        self.address_label = Label(
            text="",
            font=load_font(size=72, family=FontFamily.NOTOSANS_REGULAR),
            color=Color.WHITE.rgb(),
            pos=(self._w // 2, self._h // 2 + su(40)),
            center=True,
            antialias=True,
        )

        status_font = load_font(size=44, family=FontFamily.PIXEL_TYPE)
        self.status_label = Label(
            text="",
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
        self.continue_button = Button(
            rect=(
                start_x + button_width + button_gap,
                btn_y,
                button_width,
                button_height,
            ),
            text="Continue",
            text_visible=True,
            font=load_font(size=40, family=FontFamily.PIXEL_TYPE),
            antialias=True,
            events=ButtonEvents(
                pressed=LISTENER_CONTINUE_PRESSED,
                released=LISTENER_CONTINUE_RELEASED,
            ),
        )

        self.btns = ButtonGroup()
        self.btns.add(self.continue_button, self.cancel_button)

        self.ui_layer.add(
            self.title_label,
            self.address_label,
            self.status_label,
            self.error_label,
            *self.btns.sprites(),
        )

    def set_address(self, address: str):
        self.address_label.set_text(address)

    def set_status(self, text: str):
        self.status_label.set_text(text)
        if text:
            self.error_label.set_text("")
        self.release_presses(self.ui_layer, self.btns)

    def set_error(self, text: str):
        self.error_label.set_text(text)
        if text:
            self.status_label.set_text("")

    # ------------------------------------------------------------------
    # context
    # ------------------------------------------------------------------
    def _info_lines(self) -> list[str]:
        return [
            f"{self._feed_label} sends telemetry to an address you",
            "configure in its own settings, rather than the other",
            "way around. Enter the address below there, then",
            "press Continue.",
        ]

    def reset(self, ctx=None) -> None:
        ctx = ctx or ListenerSetupContext()
        self._feed_label = ctx.feed_label or "your game"
        rendered = [line for line in self._info_lines() if line]
        for label, text in zip(self.info_labels, rendered):
            label.set_text(text)

        # A failed install / no-network error from a previous visit
        # would otherwise still be on screen before the state writes
        # anything of its own.
        self.status_label.set_text("")
        self.error_label.set_text("")
        self.address_label.set_text("")

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
