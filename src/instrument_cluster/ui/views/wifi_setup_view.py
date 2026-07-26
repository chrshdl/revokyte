"""Wi-Fi provisioning UI.

Three phases live in one view, switched by the owning ``WifiSetupState``:

* **scan**     — a tappable list of nearby networks (+ a hidden-SSID option),
  provided by :class:`~..widgets.wifi.WifiNetworkList`.
* **password** — SSID/password fields fed by an on-screen QWERTY keyboard
  (:class:`~..widgets.wifi.WifiKeyboard`).
* **status**   — a centered message while scanning/connecting or on error.

Unlike the dashboard, this screen redraws fully every frame (the network list
and keyboard are rebuilt as the user navigates). That keeps dynamic
add/remove of widgets trivial at no real cost — it's a setup screen, not the
60 fps racing view.
"""

from __future__ import annotations

import pygame

from ...core.system.wifi_manager import Network
from ...peripherals.display import active_profile
from ..colors import Color
from ..constants import (
    HEADER_BACKBUTTON_POSITION,
    HEADER_BACKBUTTON_SIZE,
    HEADER_TITLE_FONT_SIZE,
    HEADER_TITLE_TOPLEFT,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from ..events import (
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
    WIFI_RESCAN_PRESSED,
    WIFI_RESCAN_RELEASED,
    WIFI_REVEAL_PRESSED,
    WIFI_REVEAL_RELEASED,
    WIFI_SKIP_PRESSED,
    WIFI_SKIP_RELEASED,
)
from ..utils import FontFamily, load_font, spos, srect, su, sx, sy
from ..widgets.base.button import Button, ButtonEvents
from ..widgets.base.label import Label
from ..widgets.base.line import Line
from ..widgets.base.textfield import TextField
from ..widgets.wifi import WifiKeyboard, WifiNetworkList
from .base import View


class WifiSetupView(View):
    PHASE_SCAN = "scan"
    PHASE_PASSWORD = "password"
    PHASE_STATUS = "status"
    PHASE_CONNECTED = "connected"

    def __init__(self, show_back: bool = True, show_skip: bool = False):
        self.background_color = Color.BLACK.rgb()
        self.show_back = show_back
        self.show_skip = show_skip

        self.phase = self.PHASE_SCAN
        self.status_message = ""
        self.status_is_error = False
        self.hint_message = ""

        self.network_list = WifiNetworkList()
        self.keyboard = WifiKeyboard()

        # text fields (created per password screen)
        self.ssid_field: TextField | None = None
        self.password_field: TextField | None = None
        self._focused: TextField | None = None

        self._connected_ssid: str = ""

        self._line = Line()
        self._title = Label(
            text="Connect to Wi-Fi",
            font=load_font(
                size=HEADER_TITLE_FONT_SIZE, family=FontFamily.NOTOSANS_LIGHT
            ),
            color=Color.WHITE.rgb(),
            pos=spos(*HEADER_TITLE_TOPLEFT),
            center=False,
        )
        self._back_button = self._make_back_button()

        # currently active drawables
        self._widgets: list = []

    # ------------------------------------------------------------------
    # shared widgets
    # ------------------------------------------------------------------
    def _make_back_button(self) -> Button:
        return Button(
            rect=srect(*HEADER_BACKBUTTON_POSITION, *HEADER_BACKBUTTON_SIZE),
            text="x",
            text_visible=False,
            events=ButtonEvents(
                pressed=BUTTON_BACK_PRESSED,
                released=BUTTON_BACK_RELEASED,
            ),
            font=load_font(size=50, family=FontFamily.PIXEL_TYPE),
            antialias=True,
            icon="",
            icon_color=Color.WHITE.rgb(),
            icon_size=48,
            icon_position="center",
        )

    def _header_widgets(self) -> list:
        widgets: list = [self._title]
        if self.show_back:
            widgets.append(self._back_button)
        return widgets

    # ------------------------------------------------------------------
    # phase: scan
    # ------------------------------------------------------------------
    def show_scanning(self) -> None:
        self.phase = self.PHASE_SCAN
        self.network_list.clear()
        self.status_message = "Scanning  for  networks ..."
        self.status_is_error = False
        self.hint_message = ""
        self._widgets = self._header_widgets() + self._scan_controls()

    def show_networks(self, networks: list[Network], current_ssid: str = "") -> None:
        self.phase = self.PHASE_SCAN
        self.network_list.set_networks(networks, current_ssid)
        self.status_message = "" if networks else "No  networks  found.  Try  rescan."
        self.status_is_error = False
        self.hint_message = ""
        self._widgets = (
            self._header_widgets() + self._scan_controls() + [self.network_list]
        )

    def _scan_controls(self) -> list[Button]:
        controls = [self._rescan_button()]
        if self.show_skip:
            controls.append(self._skip_button())
        return controls

    def _rescan_button(self) -> Button:
        # Sits left of the back/skip button, or hard right when it is alone.
        width = 180
        if self.show_back or self.show_skip:
            x = HEADER_BACKBUTTON_POSITION[0] - HEADER_BACKBUTTON_SIZE[0] - width
        else:
            x = 1280 - 12 - width
        return Button(
            rect=srect(x, 12, width, 70),
            text="Scan",
            text_visible=True,
            font=load_font(size=40, family=FontFamily.PIXEL_TYPE),
            antialias=True,
            events=ButtonEvents(
                pressed=WIFI_RESCAN_PRESSED,
                released=WIFI_RESCAN_RELEASED,
            ),
            icon="",
            icon_size=40,
            icon_position="left",
            icon_gap=su(10),
            text_color=Color.WHITE.rgb(),
            text_offset_y=su(6),
        )

    def _skip_button(self) -> Button:
        return Button(
            rect=srect(*HEADER_BACKBUTTON_POSITION, *HEADER_BACKBUTTON_SIZE),
            text="x",
            text_visible=False,
            events=ButtonEvents(
                pressed=WIFI_SKIP_PRESSED,
                released=WIFI_SKIP_RELEASED,
            ),
            font=load_font(size=50, family=FontFamily.PIXEL_TYPE),
            antialias=True,
            icon="",
            icon_color=Color.WHITE.rgb(),
            icon_size=48,
            icon_position="center",
        )

    # ------------------------------------------------------------------
    # phase: password / keyboard
    # ------------------------------------------------------------------
    def show_password(self, ssid: str | None, secured: bool, manual: bool) -> None:
        self.phase = self.PHASE_PASSWORD
        self.status_message = ""
        self.status_is_error = False
        self.hint_message = ""
        self.keyboard.reset()

        label_font = load_font(size=40, family=FontFamily.PIXEL_TYPE)
        field_font = load_font(size=36, family=FontFamily.NOTOSANS_REGULAR)

        self.ssid_field = None
        self.password_field = None

        statics: list = [self._title, self._back_button]
        statics.append(
            Label(
                text="Network",
                font=label_font,
                color=Color.WHITE.rgb(),
                pos=spos(40, 118),
                center=False,
            )
        )

        if manual:
            self.ssid_field = TextField(
                text="",
                font=field_font,
                color=Color.WHITE.rgb(),
                pos=spos(360, 110),
                width=sx(560),
                height=sy(64),
            )
        else:
            # SSID as a separate value label (NotoSans for glyph coverage),
            # aligned where the manual-entry field sits.
            statics.append(
                Label(
                    text=ssid or "",
                    font=field_font,
                    color=Color.WHITE.rgb(),
                    pos=spos(360, 122),
                    center=False,
                )
            )

        statics.append(
            Label(
                text="Password",
                font=label_font,
                color=Color.WHITE.rgb(),
                pos=spos(40, 196),
                center=False,
            )
        )
        self.password_field = TextField(
            text="",
            font=field_font,
            color=Color.WHITE.rgb(),
            pos=spos(360, 188),
            width=sx(500),
            height=sy(64),
            mask=True,
        )
        self._eye_button = Button(
            rect=srect(872, 188, 64, 64),
            text="",
            text_visible=False,
            font=label_font,
            antialias=True,
            events=ButtonEvents(
                pressed=WIFI_REVEAL_PRESSED,
                released=WIFI_REVEAL_RELEASED,
            ),
            icon="",  # visibility
            icon_size=40,
            icon_position="center",
            icon_color=Color.WHITE.rgb(),
        )

        self._static_password = statics
        self._set_focus(self.ssid_field if manual else self.password_field)
        self._rebuild_password_widgets()

    def _rebuild_password_widgets(self) -> None:
        fields = [f for f in (self.ssid_field, self.password_field) if f is not None]
        self._widgets = (
            self._static_password
            + fields
            + [self._eye_button]
            + self.keyboard.build()
        )

    def toggle_shift(self) -> None:
        if self.keyboard.toggle_shift():
            self._rebuild_password_widgets()

    def toggle_mode(self) -> None:
        if self.keyboard.toggle_mode():
            self._rebuild_password_widgets()

    def toggle_reveal(self) -> None:
        if self.password_field is not None:
            self.password_field.set_reveal(not self.password_field._reveal)

    # ------------------------------------------------------------------
    # focus / text access
    # ------------------------------------------------------------------
    def _set_focus(self, field: TextField | None) -> None:
        self._focused = field
        for f in (self.ssid_field, self.password_field):
            if f is not None:
                f.active = f is field
                f._rebuild_image()

    def active_field(self) -> TextField | None:
        return self._focused

    def ssid_text(self) -> str:
        return self.ssid_field.text.strip() if self.ssid_field else ""

    def password_text(self) -> str:
        return self.password_field.text if self.password_field else ""

    def set_hint(self, message: str) -> None:
        self.hint_message = message

    # ------------------------------------------------------------------
    # phase: status / connected
    # ------------------------------------------------------------------
    def show_status(
        self, message: str, error: bool = False, show_header: bool = False
    ) -> None:
        self.phase = self.PHASE_STATUS
        self.status_message = message
        self.status_is_error = error
        self._widgets = self._header_widgets() if (error or show_header) else []

    def show_connected(self, ssid: str) -> None:
        self.network_list.reset()
        self.phase = self.PHASE_CONNECTED
        self._connected_ssid = ssid
        # Clear the "Connecting to ..." status — it would otherwise linger
        # as a footer under the connected screen.
        self.status_message = ""
        self.status_is_error = False
        self.hint_message = ""
        self._widgets = []

    # ------------------------------------------------------------------
    # draw / update / events
    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        for w in self._widgets:
            w.update(dt)

    def draw_static_elements(self, background_surface) -> None:
        # Immediate-mode view: nothing baked into the background.
        pass

    def _blit(self, widget, surface) -> None:
        if hasattr(widget, "draw"):
            widget.draw(surface)
        elif getattr(widget, "visible", True):
            surface.blit(widget.image, widget.rect)

    def draw(self, surface, background):
        surface.fill(self.background_color)
        self._line.draw(surface)

        for widget in self._widgets:
            self._blit(widget, surface)

        if self.phase == self.PHASE_CONNECTED:
            self._draw_connected(surface)

        if self.phase == self.PHASE_STATUS and self.status_message:
            self._draw_centered_status(surface)
        elif self.status_message:
            self._draw_footer_status(surface)

        if self.hint_message:
            self._draw_hint(surface)

        return [surface.get_rect()]

    def full_paint(self, surface, background):
        self.draw(surface, background)

    def _draw_connected(self, surface) -> None:
        cx = sx(SCREEN_WIDTH // 2)
        cy = sy(SCREEN_HEIGHT // 2)

        icon_font = load_font(size=160, family=FontFamily.MATERIAL_SYMBOLS)
        icon = icon_font.render("", True, Color.LIGHT_GREEN.rgb())
        surface.blit(icon, icon.get_rect(center=(cx, cy - sy(50))))

        text_font = load_font(size=44, family=FontFamily.NOTOSANS_LIGHT)
        text = text_font.render(self._connected_ssid, True, Color.WHITE.rgb())
        surface.blit(text, text.get_rect(center=(cx, cy + sy(90))))

    def _draw_centered_status(self, surface) -> None:
        # NotoSans, not the pixel font: "Connecting to {ssid}" embeds
        # arbitrary network names.
        font = load_font(size=48, family=FontFamily.NOTOSANS_LIGHT)
        color = Color.LIGHT_RED.rgb() if self.status_is_error else Color.WHITE.rgb()
        text = font.render(self.status_message, True, color)
        rect = text.get_rect(center=(sx(SCREEN_WIDTH // 2), sy(SCREEN_HEIGHT // 2)))
        surface.blit(text, rect)

    def _draw_footer_status(self, surface) -> None:
        font = load_font(size=40, family=FontFamily.PIXEL_TYPE)
        color = (
            Color.LIGHT_RED.rgb() if self.status_is_error else Color.LIGHT_GREY.rgb()
        )
        text = font.render(self.status_message, True, color)
        rect = text.get_rect(center=(sx(SCREEN_WIDTH // 2), sy(SCREEN_HEIGHT) - sy(40)))
        surface.blit(text, rect)

    def _draw_hint(self, surface) -> None:
        font = load_font(size=36, family=FontFamily.PIXEL_TYPE)
        text = font.render(self.hint_message, True, Color.LIGHT_RED.rgb())
        rect = text.get_rect(center=(sx(SCREEN_WIDTH // 2), sy(SCREEN_HEIGHT) - sy(40)))
        surface.blit(text, rect)

    def handle_event(self, event) -> bool:
        # The network list gets first crack in the scan phase: its tap/drag
        # gesture machinery may consume the event entirely.
        if (
            self.phase == self.PHASE_SCAN
            and self.network_list in self._widgets
            and self.network_list.handle_event(event)
        ):
            return False

        for widget in self._widgets:
            if widget is self.network_list:
                continue  # already dispatched above
            handler = getattr(widget, "handle_event", None)
            if handler is not None:
                handler(event)

        # Focus management for the password phase: tap a field to type into it.
        if self.phase == self.PHASE_PASSWORD and event.type in (
            pygame.FINGERDOWN,
            pygame.MOUSEBUTTONDOWN,
        ):
            xy = active_profile().to_logical(event)
            if xy:
                for field in (self.ssid_field, self.password_field):
                    if field is not None and field.rect.collidepoint(xy):
                        self._set_focus(field)
                        break
        return False
