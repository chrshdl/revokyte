from dataclasses import dataclass
from pygame.sprite import LayeredDirty

from ...ui.colors import Color
from ...ui.events import (
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
    INSTALL_PRESSED,
    INSTALL_RELEASED,
)
from ...ui.skins import active_skin
from ...ui.utils import FontFamily, load_font, su
from ...ui.widgets.base.button import Button, ButtonEvents, ButtonGroup
from ...ui.widgets.base.label import Label
from .base import View
from .header import header_line, header_title


@dataclass(frozen=True)
class InstallContext:
    """What InstallView rebinds on every entry (was its constructor args)."""

    feed_label: str | None = None
    updating: bool = False


class InstallView(View):
    def __init__(self, feed_label: str = None, updating: bool = False):
        self.ui_layer = LayeredDirty()
        self.background_color = Color.BLACK.rgb()

        self._w, self._h = active_skin().size
        self._feed_label = feed_label or "your game"
        self._updating = updating

        self._init_ui_elements()

    def _init_ui_elements(self):
        self.title_label = header_title(
            "Updating UDP Telemetry"
            if self._updating
            else "Install UDP Telemetry?"
        )
        self.horizontal_line = header_line()

        info_font = load_font(size=44, family=FontFamily.PIXEL_TYPE)
        info_lines = self._info_lines()

        self.info_labels = []
        x = self._w // 8 - su(4)
        y = self._h // 4 - su(16)
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
        start_x, btn_y = self._button_origin()

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

        self.install_button = Button(
            rect=(
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
        self.ui_layer.add(self.title_label, self.status_label, self.error_label)
        self._layout_buttons()

    # ------------------------------------------------------------------
    # context
    # ------------------------------------------------------------------
    def _info_lines(self) -> list[str]:
        """The prose, interpolated with the current context. The blank
        entries are spacers; the number of *rendered* lines is fixed either
        way, which is what lets reset() retext the existing labels in place
        instead of rebuilding them."""
        return [
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

    def _button_origin(self) -> tuple[int, int]:
        # An update starts on its own, so Install would be a dead control on
        # a screen that is already installing — Cancel alone, centred.
        button_width = su(220)
        button_gap = su(60)
        buttons = 1 if self._updating else 2
        total_width = button_width * buttons + button_gap * (buttons - 1)
        return (self._w - total_width) // 2, self._h // 2 + su(200)

    def _layout_buttons(self) -> None:
        """Place and enrol the buttons the current context calls for. Both
        Buttons always exist; only which of them is live changes."""
        start_x, btn_y = self._button_origin()
        self.cancel_button.rect.topleft = (start_x, btn_y)
        self.install_button.rect.topleft = (
            start_x + su(220) + su(60),
            btn_y,
        )
        for button in (self.cancel_button, self.install_button):
            self.btns.remove(button)
            self.ui_layer.remove(button)
        if self._updating:
            self.btns.add(self.cancel_button)
        else:
            self.btns.add(self.install_button, self.cancel_button)
        self.ui_layer.add(*self.btns.sprites())

    def reset(self, ctx=None) -> None:
        ctx = ctx or InstallContext()
        self._feed_label = ctx.feed_label or "your game"
        self._updating = bool(ctx.updating)

        self.title_label.set_text(
            "Updating UDP Telemetry" if self._updating else "Install UDP Telemetry?"
        )
        rendered = [line for line in self._info_lines() if line]
        for label, text in zip(self.info_labels, rendered):
            label.set_text(text)

        # A failed install / no-network error from a previous visit
        # would otherwise still be on screen before the state writes
        # anything of its own.
        self.status_label.set_text("")
        self.error_label.set_text("")
        self.release_presses(self.ui_layer, self.btns)
        self._layout_buttons()

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
