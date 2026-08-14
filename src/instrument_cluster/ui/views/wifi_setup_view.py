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
from ..icons import Icon
from ..events import (
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
    WIFI_BACKSPACE_PRESSED,
    WIFI_BACKSPACE_RELEASED,
    WIFI_RESCAN_PRESSED,
    WIFI_RESCAN_RELEASED,
    WIFI_SKIP_PRESSED,
    WIFI_SKIP_RELEASED,
)
from ..skins import active_skin
from ..utils import FontFamily, load_font, load_font_px, su
from ..widgets.base.button import Button, ButtonEvents
from ..widgets.base.label import Label
from ..widgets.base.textfield import TextField
from ..widgets.wifi import WifiKeyboard, WifiNetworkList
from .base import View
from .header import corner_button, corner_button_rect, header_line, header_title


def _kb_left() -> float:
    # Password-row geometry: field plus delete key span exactly the
    # keyboard's width (the ten-key rows are centered on the screen).
    skin = active_skin()
    kb = skin.keyboard
    return (skin.width - (10 * kb.key_w + 9 * kb.gap)) / 2


def _del_x() -> float:
    skin = active_skin()
    return skin.width - _kb_left() - skin.keyboard.special_w


class WifiSetupView(View):
    PHASE_SCAN = "scan"
    PHASE_PASSWORD = "password"
    PHASE_STATUS = "status"
    PHASE_CONNECTED = "connected"

    _DEFAULT_TITLE = "Connect to Wi-Fi"

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

        self._line = header_line()
        self._title = header_title(self._DEFAULT_TITLE)
        self._back_button = self._make_back_button()

        # currently active drawables
        self._widgets: list = []

    # ------------------------------------------------------------------
    # shared widgets
    # ------------------------------------------------------------------
    def _make_back_button(self) -> Button:
        return corner_button(
            icon=Icon.CLOSE.glyph(),
            events=ButtonEvents(
                pressed=BUTTON_BACK_PRESSED,
                released=BUTTON_BACK_RELEASED,
            ),
        )

    def _set_title(self, text: str) -> None:
        self._title.set_text(text)

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
        self._set_title(self._DEFAULT_TITLE)
        self.network_list.clear()
        self.status_message = "Scanning  for  networks ..."
        self.status_is_error = False
        self.hint_message = ""
        self._widgets = self._header_widgets() + self._scan_controls()

    def show_unavailable(self) -> None:
        """Radio unreachable — distinct from a scan that found nothing, so
        the user isn't told to hunt for their router when the device's own
        Wi-Fi stack is the problem."""
        self.phase = self.PHASE_SCAN
        self._set_title(self._DEFAULT_TITLE)
        self.network_list.clear()
        self.status_message = "Wi-Fi  hardware  not  responding.  Try  rescan."
        self.status_is_error = True
        self.hint_message = ""
        self._widgets = self._header_widgets() + self._scan_controls()

    def show_networks(self, networks: list[Network], current_ssid: str = "") -> None:
        self.phase = self.PHASE_SCAN
        self._set_title(self._DEFAULT_TITLE)
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
        skin = active_skin()
        kb = skin.keyboard
        width, height = kb.rescan_size
        corner = corner_button_rect()
        if self.show_back or self.show_skip:
            x = corner[0] - corner[2] - width
        else:
            x = skin.width - skin.header.back_button_gap - width
        return Button(
            rect=(x, corner[1], width, height),
            text="Scan",
            text_visible=True,
            font=load_font_px(
                kb.rescan_font, FontFamily[kb.rescan_font_family]
            ),
            antialias=True,
            events=ButtonEvents(
                pressed=WIFI_RESCAN_PRESSED,
                released=WIFI_RESCAN_RELEASED,
            ),
            icon=Icon.RESCAN.glyph(),
            icon_size=kb.rescan_font,
            icon_font=load_font_px(kb.rescan_font, FontFamily.MATERIAL_SYMBOLS),
            icon_position="left",
            icon_gap=su(10),
            text_color=Color.WHITE.rgb(),
            text_offset_y=su(6),
        )

    def _skip_button(self) -> Button:
        return corner_button(
            icon=Icon.CLOSE.glyph(),
            events=ButtonEvents(
                pressed=WIFI_SKIP_PRESSED,
                released=WIFI_SKIP_RELEASED,
            ),
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

        skin = active_skin()
        kb = skin.keyboard
        label_font = load_font_px(
            kb.manual_label_font, FontFamily[kb.manual_label_font_family]
        )

        self.ssid_field = None
        self.password_field = None

        statics: list = [self._title, self._back_button]

        if manual:
            self._set_title(self._DEFAULT_TITLE)
            statics.append(
                Label(
                    text="Network",
                    font=label_font,
                    color=Color.WHITE.rgb(),
                    pos=kb.manual_ssid_label_pos,
                    center=False,
                )
            )
            # SSIDs are arbitrary user text — NotoSans covers accents and
            # non-Latin scripts the pixel font lacks.
            fx, fy, fw, fh = kb.manual_field_rect
            self.ssid_field = TextField(
                text="",
                font=load_font_px(
                    kb.manual_field_font,
                    FontFamily[kb.manual_field_font_family],
                ),
                color=Color.WHITE.rgb(),
                pos=(fx, fy),
                width=fw,
                height=fh,
            )
            statics.append(
                Label(
                    text="Password",
                    font=label_font,
                    color=Color.WHITE.rgb(),
                    pos=kb.manual_pw_label_pos,
                    center=False,
                )
            )
            pw_left = kb.manual_pw_left
        else:
            # The picked network is named in the header, so the password row
            # is the only field chrome on screen.
            self._set_title(f"Enter Password for  {ssid or ''}")
            pw_left = _kb_left()

        self.password_field = TextField(
            text="",
            font=load_font_px(kb.pw_font, FontFamily[kb.pw_font_family]),
            color=Color.WHITE.rgb(),
            pos=(round(pw_left), kb.pw_row_y),
            # Same breathing room to the delete key as between character keys.
            width=round(_del_x() - kb.gap - pw_left),
            height=kb.pw_row_h,
            mask=True,
        )
        # Delete sits flush against the field, EnterIPView-style; the
        # password-reveal eye lives on the keyboard where backspace was.
        self._del_button = Button(
            rect=(round(_del_x()), kb.pw_row_y, kb.special_w, kb.pw_row_h),
            text="<",
            text_visible=False,
            font=label_font,
            antialias=True,
            events=ButtonEvents(
                pressed=WIFI_BACKSPACE_PRESSED,
                released=WIFI_BACKSPACE_RELEASED,
            ),
            icon=Icon.BACKSPACE.glyph(),
            icon_size=46,
            icon_position="center",
            icon_color=Color.WHITE.rgb(),
            # Invisible text carries the color the pressed border derives
            # from (see Button._compute_border_color) \u2014 same trick as
            # EnterIPView's delete button.
            text_color=Color.LIGHT_RED.rgb(),
            pressed_gradient=(Color.RPM_DARK_RED.rgb(), Color.BLACK.rgb()),
            border_top_left_radius=4,
            border_top_right_radius=4,
            border_bottom_left_radius=4,
            border_bottom_right_radius=4,
        )
        self._static_password = statics
        self._set_focus(self.ssid_field if manual else self.password_field)
        self._rebuild_password_widgets()

    def _rebuild_password_widgets(self) -> None:
        fields = [f for f in (self.ssid_field, self.password_field) if f is not None]
        self._widgets = (
            self._static_password + fields + [self._del_button] + self.keyboard.build()
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
        self._set_title(self._DEFAULT_TITLE)
        self.status_message = message
        self.status_is_error = error
        self._widgets = self._header_widgets() if (error or show_header) else []

    def show_connected(self, ssid: str) -> None:
        self.network_list.reset()
        self.phase = self.PHASE_CONNECTED
        self._set_title(self._DEFAULT_TITLE)
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
        skin = active_skin()
        cx = skin.width // 2
        cy = skin.height // 2

        icon_font = load_font(size=160, family=FontFamily.MATERIAL_SYMBOLS)
        icon = icon_font.render(Icon.CONNECTED.glyph(), True, Color.LIGHT_GREEN.rgb())
        surface.blit(icon, icon.get_rect(center=(cx, cy - su(50))))

        text_font = load_font(size=44, family=FontFamily.NOTOSANS_LIGHT)
        text = text_font.render(self._connected_ssid, True, Color.WHITE.rgb())
        surface.blit(text, text.get_rect(center=(cx, cy + su(90))))

    def _draw_centered_status(self, surface) -> None:
        # NotoSans, not the pixel font: "Connecting to {ssid}" embeds
        # arbitrary network names.
        font = load_font(size=48, family=FontFamily.NOTOSANS_LIGHT)
        color = Color.LIGHT_RED.rgb() if self.status_is_error else Color.WHITE.rgb()
        text = font.render(self.status_message, True, color)
        skin = active_skin()
        rect = text.get_rect(center=(skin.width // 2, skin.height // 2))
        surface.blit(text, rect)

    def _draw_footer_status(self, surface) -> None:
        font = load_font(size=40, family=FontFamily.PIXEL_TYPE)
        color = (
            Color.LIGHT_RED.rgb() if self.status_is_error else Color.LIGHT_GREY.rgb()
        )
        text = font.render(self.status_message, True, color)
        skin = active_skin()
        rect = text.get_rect(center=(skin.width // 2, skin.height - su(40)))
        surface.blit(text, rect)

    def _draw_hint(self, surface) -> None:
        font = load_font(size=36, family=FontFamily.PIXEL_TYPE)
        text = font.render(self.hint_message, True, Color.LIGHT_RED.rgb())
        skin = active_skin()
        rect = text.get_rect(center=(skin.width // 2, skin.height - su(40)))
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
