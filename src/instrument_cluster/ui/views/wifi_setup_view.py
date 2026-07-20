"""Wi-Fi provisioning UI.

Three phases live in one view, switched by the owning ``WifiSetupState``:

* **scan**     — a tappable list of nearby networks (+ a hidden-SSID option).
* **password** — an on-screen QWERTY keyboard feeding SSID/password fields.
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
    WIFI_KEY_GAP,
    WIFI_KEY_H,
    WIFI_KEY_ROW_STEP,
    WIFI_KEY_W,
    WIFI_KEYBOARD_TOP,
    WIFI_LIST_TOP,
    WIFI_LIST_X,
    WIFI_MAX_ROWS,
    WIFI_ROW_GAP,
    WIFI_ROW_HEIGHT,
    WIFI_ROW_WIDTH,
    WIFI_SPACE_W,
    WIFI_SPECIAL_W,
)
from ..events import (
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
    WIFI_BACKSPACE_PRESSED,
    WIFI_BACKSPACE_RELEASED,
    WIFI_CONNECT_PRESSED,
    WIFI_CONNECT_RELEASED,
    WIFI_KEY_PRESSED,
    WIFI_KEY_RELEASED,
    WIFI_MODE_PRESSED,
    WIFI_MODE_RELEASED,
    WIFI_NETWORK_ROW_PRESSED,
    WIFI_NETWORK_SELECTED,
    WIFI_OTHER_ROW_PRESSED,
    WIFI_OTHER_SELECTED,
    WIFI_RESCAN_PRESSED,
    WIFI_RESCAN_RELEASED,
    WIFI_REVEAL_PRESSED,
    WIFI_REVEAL_RELEASED,
    WIFI_SHIFT_PRESSED,
    WIFI_SHIFT_RELEASED,
    WIFI_SKIP_PRESSED,
    WIFI_SKIP_RELEASED,
)
from ..utils import FontFamily, load_font, spos, srect, su, sx, sy
from ..widgets.base.button import Button, ButtonEvents
from ..widgets.base.label import Label
from ..widgets.base.line import Line
from ..widgets.base.textfield import TextField
from .base import View

_LETTER_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
_SYMBOL_ROWS = ["1234567890", '-/:;()&@"', ".,?!'+="]


class WifiSetupView(View):
    PHASE_SCAN = "scan"
    PHASE_PASSWORD = "password"
    PHASE_STATUS = "status"
    PHASE_CONNECTED = "connected"

    # scrollbar geometry (design-space px)
    _SB_W = 8  # visual bar width
    _SB_RIGHT = 16  # margin between bar right and screen right edge
    _SB_PAD = 20  # gap between row content and bar (clears hit zone)
    _SB_MIN_THUMB = 32  # minimum thumb height
    _DRAG_THRESHOLD = 15  # design-px movement before a touch becomes a drag

    def __init__(self, show_back: bool = True, show_skip: bool = False):
        self.background_color = Color.BLACK.rgb()
        self.show_back = show_back
        self.show_skip = show_skip

        self.phase = self.PHASE_SCAN
        self.status_message = ""
        self.status_is_error = False
        self.hint_message = ""

        # password-phase keyboard state
        self._shift = False
        self._symbols = False

        # text fields (created per password screen)
        self.ssid_field: TextField | None = None
        self.password_field: TextField | None = None
        self._focused: TextField | None = None

        # network rows kept for manual signal-bar / lock rendering
        self._network_rows: list[tuple[Button, Network]] = []
        self._all_networks: list[Network] = []
        self._scroll_offset: int = 0
        self._other_btn: Button | None = None
        self._connected_ssid: str = ""
        self._current_ssid: str = ""

        # tap/drag disambiguation state
        self._gesture_id: int | None = None
        self._gesture_start: tuple[float, float] | None = None
        self._gesture_event = None
        self._gesture_drag: bool = False
        self._gesture_scroll_base: int = 0

        # scrollbar drag state
        self._sb_dragging: bool = False
        self._sb_finger_id: int | None = None

        self._icon_font = load_font(size=30, family=FontFamily.MATERIAL_SYMBOLS)
        self._line = Line()
        self._title = Label(
            text="Connect  to  Wi-Fi",
            font=load_font(size=HEADER_TITLE_FONT_SIZE, family=FontFamily.PIXEL_TYPE),
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
        self._reset_scroll_state()
        self.phase = self.PHASE_SCAN
        self._network_rows = []
        self.status_message = "Scanning  for  networks ..."
        self.status_is_error = False
        self.hint_message = ""
        self._widgets = self._header_widgets() + self._scan_controls()

    def show_networks(self, networks: list[Network], current_ssid: str = "") -> None:
        self._reset_scroll_state()
        self._all_networks = networks
        self._current_ssid = current_ssid
        self._scroll_offset = 0
        self._rebuild_network_list()

    def _rebuild_network_list(self) -> None:
        networks = self._all_networks
        scrollable = len(networks) > WIFI_MAX_ROWS
        row_w = (
            SCREEN_WIDTH - WIFI_LIST_X - self._SB_W - self._SB_RIGHT - self._SB_PAD
            if scrollable
            else WIFI_ROW_WIDTH
        )

        self.phase = self.PHASE_SCAN
        self.status_message = "" if networks else "No  networks  found.  Try  rescan."
        self.status_is_error = False
        self.hint_message = ""

        widgets = self._header_widgets() + self._scan_controls()
        self._network_rows = []

        y = WIFI_LIST_TOP
        for net in networks[self._scroll_offset : self._scroll_offset + WIFI_MAX_ROWS]:
            button = self._network_button(y, net, row_w)
            self._network_rows.append((button, net))
            widgets.append(button)
            y += WIFI_ROW_HEIGHT + WIFI_ROW_GAP

        self._other_btn = self._other_button(y, row_w)
        widgets.append(self._other_btn)
        self._widgets = widgets

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
            icon="\ue5d5",
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

    def _network_button(
        self, y: float, net: Network, width: int = WIFI_ROW_WIDTH
    ) -> Button:
        return Button(
            rect=srect(WIFI_LIST_X, y, width, WIFI_ROW_HEIGHT),
            text=net.ssid,
            text_visible=True,
            # SSIDs are arbitrary user text — NotoSans covers accents and
            # non-Latin scripts the pixel font lacks.
            font=load_font(size=40, family=FontFamily.NOTOSANS_LIGHT),
            antialias=True,
            events=ButtonEvents(
                pressed=WIFI_NETWORK_ROW_PRESSED,
                released=WIFI_NETWORK_SELECTED,
            ),
            event_data={"ssid": net.ssid, "secured": net.secured},
            content_align="left",
            padding=(su(24), 0, su(24), 0),
            text_color=Color.WHITE.rgb(),
        )

    def _other_button(self, y: float, width: int = WIFI_ROW_WIDTH) -> Button:
        return Button(
            rect=srect(WIFI_LIST_X, y, width, WIFI_ROW_HEIGHT),
            text="Enter network manually ...",
            text_visible=True,
            font=load_font(size=40, family=FontFamily.NOTOSANS_LIGHT),
            antialias=True,
            events=ButtonEvents(
                pressed=WIFI_OTHER_ROW_PRESSED,
                released=WIFI_OTHER_SELECTED,
            ),
            content_align="left",
            padding=(su(24), 0, su(24), 0),
            text_color=Color.WHITE.rgb(),
        )

    # ------------------------------------------------------------------
    # phase: password / keyboard
    # ------------------------------------------------------------------
    def show_password(self, ssid: str | None, secured: bool, manual: bool) -> None:
        self.phase = self.PHASE_PASSWORD
        self.status_message = ""
        self.status_is_error = False
        self.hint_message = ""
        self._shift = False
        self._symbols = False

        label_font = load_font(size=40, family=FontFamily.PIXEL_TYPE)
        field_font = load_font(size=36, family=FontFamily.NOTOSANS_REGULAR)

        self.ssid_field = None
        self.password_field = None

        statics: list = [self._title, self._back_button]

        if manual:
            statics.append(
                Label(
                    text="Network",
                    font=label_font,
                    color=Color.WHITE.rgb(),
                    pos=spos(40, 118),
                    center=False,
                )
            )
            self.ssid_field = TextField(
                text="",
                font=field_font,
                color=Color.WHITE.rgb(),
                pos=spos(360, 110),
                width=sx(560),
                height=sy(64),
            )
        else:
            statics.append(
                Label(
                    text="Network",
                    font=label_font,
                    color=Color.WHITE.rgb(),
                    pos=spos(40, 118),
                    center=False,
                )
            )
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
            self._static_password + fields + [self._eye_button] + self._build_keyboard()
        )

    def _build_keyboard(self) -> list[Button]:
        keys: list[Button] = []
        rows = _SYMBOL_ROWS if self._symbols else _LETTER_ROWS
        key_font = load_font(size=40, family=FontFamily.NOTOSANS_REGULAR)

        # First two rows: plain character keys, centered.
        for r in range(2):
            keys.extend(
                self._char_row(
                    rows[r], WIFI_KEYBOARD_TOP + r * WIFI_KEY_ROW_STEP, key_font
                )
            )

        # Third row: shift + chars + backspace.
        y2 = WIFI_KEYBOARD_TOP + 2 * WIFI_KEY_ROW_STEP
        chars = rows[2]
        block_w = len(chars) * WIFI_KEY_W + (len(chars) - 1) * WIFI_KEY_GAP
        total = WIFI_SPECIAL_W + WIFI_KEY_GAP + block_w + WIFI_KEY_GAP + WIFI_SPECIAL_W
        x = (1280 - total) / 2
        keys.append(
            self._special_button(
                x,
                y2,
                WIFI_SPECIAL_W,
                "",
                WIFI_SHIFT_PRESSED,
                WIFI_SHIFT_RELEASED,
                active=self._shift and not self._symbols,
            )
        )
        x += WIFI_SPECIAL_W + WIFI_KEY_GAP
        for ch in chars:
            keys.append(self._char_key(x, y2, ch, key_font))
            x += WIFI_KEY_W + WIFI_KEY_GAP
        keys.append(
            self._special_button(
                x,
                y2,
                WIFI_SPECIAL_W,
                "",
                WIFI_BACKSPACE_PRESSED,
                WIFI_BACKSPACE_RELEASED,
            )
        )

        # Fourth row: mode toggle + space + connect.
        y3 = WIFI_KEYBOARD_TOP + 3 * WIFI_KEY_ROW_STEP
        total = (
            WIFI_SPECIAL_W + WIFI_KEY_GAP + WIFI_SPACE_W + WIFI_KEY_GAP + WIFI_SPECIAL_W
        )
        x = (1280 - total) / 2
        keys.append(
            Button(
                rect=srect(x, y3, WIFI_SPECIAL_W, WIFI_KEY_H),
                text="ABC" if self._symbols else "123",
                font=load_font(size=40, family=FontFamily.PIXEL_TYPE),
                antialias=True,
                events=ButtonEvents(
                    pressed=WIFI_MODE_PRESSED, released=WIFI_MODE_RELEASED
                ),
                text_color=Color.WHITE.rgb(),
            )
        )
        x += WIFI_SPECIAL_W + WIFI_KEY_GAP
        keys.append(
            Button(
                rect=srect(x, y3, WIFI_SPACE_W, WIFI_KEY_H),
                text="space",
                font=load_font(size=36, family=FontFamily.PIXEL_TYPE),
                antialias=True,
                events=ButtonEvents(
                    pressed=WIFI_KEY_PRESSED, released=WIFI_KEY_RELEASED
                ),
                event_data={"label": " "},
                text_color=Color.LIGHT_GREY.rgb(),
            )
        )
        x += WIFI_SPACE_W + WIFI_KEY_GAP
        keys.append(
            Button(
                rect=srect(x, y3, WIFI_SPECIAL_W, WIFI_KEY_H),
                text="OK",
                font=load_font(size=44, family=FontFamily.PIXEL_TYPE),
                antialias=True,
                events=ButtonEvents(
                    pressed=WIFI_CONNECT_PRESSED, released=WIFI_CONNECT_RELEASED
                ),
                text_color=Color.GREEN.rgb(),
                pressed_gradient=(Color.DARK_GREEN.rgb(), Color.BLACK.rgb()),
            )
        )
        return keys

    def _char_row(self, chars: str, y: float, font) -> list[Button]:
        block_w = len(chars) * WIFI_KEY_W + (len(chars) - 1) * WIFI_KEY_GAP
        x = (1280 - block_w) / 2
        out = []
        for ch in chars:
            out.append(self._char_key(x, y, ch, font))
            x += WIFI_KEY_W + WIFI_KEY_GAP
        return out

    def _char_key(self, x: float, y: float, ch: str, font) -> Button:
        display = ch.upper() if (self._shift and not self._symbols) else ch
        return Button(
            rect=srect(x, y, WIFI_KEY_W, WIFI_KEY_H),
            text=display,
            font=font,
            antialias=True,
            events=ButtonEvents(pressed=WIFI_KEY_PRESSED, released=WIFI_KEY_RELEASED),
            event_data={"label": display},
            text_color=Color.WHITE.rgb(),
        )

    def _special_button(
        self, x, y, w, icon, pressed_evt, released_evt, active=False
    ) -> Button:
        return Button(
            rect=srect(x, y, w, WIFI_KEY_H),
            text="",
            text_visible=False,
            font=load_font(size=40, family=FontFamily.PIXEL_TYPE),
            antialias=True,
            events=ButtonEvents(pressed=pressed_evt, released=released_evt),
            icon=icon,
            icon_size=40,
            icon_position="center",
            icon_color=Color.BLUE.rgb() if active else Color.WHITE.rgb(),
        )

    def toggle_shift(self) -> None:
        if not self._symbols:
            self._shift = not self._shift
            self._rebuild_password_widgets()

    def toggle_mode(self) -> None:
        self._symbols = not self._symbols
        self._shift = False
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
    # phase: status
    # ------------------------------------------------------------------
    def show_status(
        self, message: str, error: bool = False, show_header: bool = False
    ) -> None:
        self.phase = self.PHASE_STATUS
        self.status_message = message
        self.status_is_error = error
        self._widgets = self._header_widgets() if (error or show_header) else []

    def show_connected(self, ssid: str) -> None:
        self._reset_scroll_state()
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

        if self.phase == self.PHASE_SCAN:
            self._draw_network_decorations(surface)
            if len(self._all_networks) > WIFI_MAX_ROWS:
                self._draw_scrollbar(surface)

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

    def _draw_network_decorations(self, surface) -> None:
        for button, net in self._network_rows:
            self._draw_signal_bars(surface, button.rect, net.bars)
            if self._current_ssid and net.ssid == self._current_ssid:
                check = self._icon_font.render("\ue876", True, Color.LIGHT_GREEN.rgb())
                r = check.get_rect()
                r.right = button.rect.right - sx(108)
                r.centery = button.rect.centery
                surface.blit(check, r)
            if net.secured:
                lock = self._icon_font.render("\ue897", True, Color.WHITE.rgb())
                r = lock.get_rect()
                r.right = button.rect.right - sx(72)
                r.centery = button.rect.centery
                surface.blit(lock, r)

    def _draw_scrollbar(self, surface) -> None:
        total = len(self._all_networks)
        visible = WIFI_MAX_ROWS

        track_w = sx(self._SB_W)
        track_x = sx(SCREEN_WIDTH - self._SB_RIGHT - self._SB_W)
        track_top = sy(WIFI_LIST_TOP)
        track_h = sy(WIFI_MAX_ROWS * (WIFI_ROW_HEIGHT + WIFI_ROW_GAP))

        pygame.draw.rect(
            surface,
            (15, 30, 60),
            pygame.Rect(track_x, track_top, track_w, track_h),
            border_radius=track_w // 2,
        )

        thumb_h = max(su(self._SB_MIN_THUMB), int(track_h * visible / total))
        max_offset = total - visible
        frac = self._scroll_offset / max_offset if max_offset > 0 else 0.0
        thumb_top = track_top + int((track_h - thumb_h) * frac)
        pygame.draw.rect(
            surface,
            Color.BLUE.rgb(),
            pygame.Rect(track_x, thumb_top, track_w, thumb_h),
            border_radius=track_w // 2,
        )

    def _draw_signal_bars(self, surface, row_rect, bars: int) -> None:
        bar_w = sx(10)
        gap = sx(6)
        base_x = row_rect.right - sx(24) - (4 * bar_w + 3 * gap)
        base_y = row_rect.centery + sy(18)
        for i in range(4):
            h = sy(10 + i * 8)
            color = Color.WHITE.rgb() if i < bars else Color.GREY.rgb()
            pygame.draw.rect(
                surface,
                color,
                pygame.Rect(base_x + i * (bar_w + gap), base_y - h, bar_w, h),
            )

    def _draw_connected(self, surface) -> None:
        cx = sx(SCREEN_WIDTH // 2)
        cy = sy(SCREEN_HEIGHT // 2)

        icon_font = load_font(size=160, family=FontFamily.MATERIAL_SYMBOLS)
        icon = icon_font.render("\ue86c", True, Color.LIGHT_GREEN.rgb())
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

    def _reset_scroll_state(self) -> None:
        """Cancel any active gesture or scrollbar drag and clear all tracking state."""
        if self._gesture_id is not None:
            self._cancel_gesture_press()
        self._gesture_id = None
        self._gesture_start = None
        self._gesture_event = None
        self._gesture_drag = False
        self._gesture_scroll_base = 0
        self._sb_dragging = False
        self._sb_finger_id = None

    def _cancel_gesture_press(self) -> None:
        """Send an out-of-bounds FINGERUP to reset any button in PRESSED state."""
        cancel = pygame.event.Event(
            pygame.FINGERUP,
            finger_id=self._gesture_id,
            touch_id=0,
            x=-1.0,
            y=-1.0,
            dx=0.0,
            dy=0.0,
            pressure=0.0,
        )
        for widget in self._widgets:
            handler = getattr(widget, "handle_event", None)
            if handler:
                handler(cancel)

    def _intercept_scan_touch(self, event) -> bool:
        """Disambiguate list taps from drag gestures.

        On FINGERDOWN, the event is forwarded to widgets immediately so the
        touched row highlights blue. The selection action fires only on a
        confirmed tap (FINGERUP with little movement). On drag the pressed
        visual is cancelled and the list scrolls instead.

        Returns True to consume the event (caller skips widget dispatch).
        """
        if event.type == pygame.FINGERDOWN:
            xy = active_profile().to_logical(event)
            if not xy:
                return False
            lx, ly = xy
            # Only intercept touches that land on a network row button.
            hit = next(
                (btn for btn, _ in self._network_rows if btn.rect.collidepoint(lx, ly)),
                None,
            )
            if (
                hit is None
                and self._other_btn
                and self._other_btn.rect.collidepoint(lx, ly)
            ):
                hit = self._other_btn
            if hit is None:
                return False
            # Forward FINGERDOWN now: button goes PRESSED (blue highlight).
            # Because pressed=WIFI_NETWORK_ROW_PRESSED (no handler), the
            # selection action does NOT fire yet.
            for widget in self._widgets:
                handler = getattr(widget, "handle_event", None)
                if handler:
                    handler(event)
            self._gesture_id = event.finger_id
            self._gesture_start = (lx, ly)
            self._gesture_event = event
            self._gesture_drag = False
            return True

        if self._gesture_id is None:
            return False

        if event.type == pygame.FINGERMOTION:
            if event.finger_id != self._gesture_id:
                return False
            xy = active_profile().to_logical(event)
            if xy and self._gesture_start:
                dx = xy[0] - self._gesture_start[0]
                dy = xy[1] - self._gesture_start[1]
                threshold = su(self._DRAG_THRESHOLD)
                if not self._gesture_drag and (
                    abs(dx) > threshold or abs(dy) > threshold
                ):
                    self._gesture_drag = True
                    self._gesture_scroll_base = self._scroll_offset
                    self._cancel_gesture_press()
                if self._gesture_drag and len(self._all_networks) > WIFI_MAX_ROWS:
                    row_h = sy(WIFI_ROW_HEIGHT + WIFI_ROW_GAP)
                    steps = -round(dy / row_h)
                    max_offset = len(self._all_networks) - WIFI_MAX_ROWS
                    new_off = max(0, min(max_offset, self._gesture_scroll_base + steps))
                    if new_off != self._scroll_offset:
                        self._scroll_offset = new_off
                        self._rebuild_network_list()
            return True

        if event.type == pygame.FINGERUP:
            if event.finger_id != self._gesture_id:
                return False
            if not self._gesture_drag:
                # Confirmed tap: deliver FINGERUP so released fires WIFI_NETWORK_SELECTED.
                for widget in self._widgets:
                    handler = getattr(widget, "handle_event", None)
                    if handler:
                        handler(event)
            # else: drag — list already scrolled in real-time during FINGERMOTION.
            self._gesture_id = None
            self._gesture_start = None
            self._gesture_event = None
            self._gesture_drag = False
            self._gesture_scroll_base = 0
            return True

        return False

    def handle_event(self, event) -> bool:
        if self.phase == self.PHASE_SCAN and self._intercept_scan_touch(event):
            return False

        for widget in self._widgets:
            handler = getattr(widget, "handle_event", None)
            if handler is not None:
                handler(event)

        # Scrollbar navigation for the scan phase.
        if self.phase == self.PHASE_SCAN and len(self._all_networks) > WIFI_MAX_ROWS:
            track_top = sy(WIFI_LIST_TOP)
            track_bottom = sy(
                WIFI_LIST_TOP + WIFI_MAX_ROWS * (WIFI_ROW_HEIGHT + WIFI_ROW_GAP)
            )
            hit_left = sx(SCREEN_WIDTH - self._SB_W - self._SB_RIGHT - self._SB_PAD)
            max_offset = len(self._all_networks) - WIFI_MAX_ROWS

            if event.type in (pygame.FINGERDOWN, pygame.MOUSEBUTTONDOWN):
                xy = active_profile().to_logical(event)
                if xy:
                    lx, ly = xy
                    if lx >= hit_left and track_top <= ly <= track_bottom:
                        self._sb_dragging = True
                        self._sb_finger_id = getattr(event, "finger_id", 0)
                        frac = (ly - track_top) / (track_bottom - track_top)
                        self._scroll_offset = max(
                            0, min(max_offset, round(frac * max_offset))
                        )
                        self._rebuild_network_list()

            elif event.type == pygame.FINGERMOTION and self._sb_dragging:
                if getattr(event, "finger_id", 0) == self._sb_finger_id:
                    xy = active_profile().to_logical(event)
                    if xy:
                        _, ly = xy
                        frac = max(
                            0.0, min(1.0, (ly - track_top) / (track_bottom - track_top))
                        )
                        new_off = max(0, min(max_offset, round(frac * max_offset)))
                        if new_off != self._scroll_offset:
                            self._scroll_offset = new_off
                            self._rebuild_network_list()

            elif (
                event.type in (pygame.FINGERUP, pygame.MOUSEBUTTONUP)
                and self._sb_dragging
            ):
                if getattr(event, "finger_id", 0) == self._sb_finger_id:
                    self._sb_dragging = False
                    self._sb_finger_id = None

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
