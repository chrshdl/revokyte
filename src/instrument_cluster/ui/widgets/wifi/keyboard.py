"""On-screen QWERTY keyboard for the Wi-Fi password phase.

Owns the shift/symbols mode state and builds the key Button widgets for
the current mode. The owning view calls :meth:`build` whenever it
rebuilds its widget list; the toggle methods report whether the mode
actually changed so the caller knows a rebuild is needed.
"""

from __future__ import annotations

from ...constants import (
    WIFI_KEY_GAP,
    WIFI_KEY_H,
    WIFI_KEY_ROW_STEP,
    WIFI_KEY_W,
    WIFI_KEYBOARD_TOP,
    WIFI_SPACE_W,
    WIFI_SPECIAL_W,
)
from ...events import (
    WIFI_BACKSPACE_PRESSED,
    WIFI_BACKSPACE_RELEASED,
    WIFI_CONNECT_PRESSED,
    WIFI_CONNECT_RELEASED,
    WIFI_KEY_PRESSED,
    WIFI_KEY_RELEASED,
    WIFI_MODE_PRESSED,
    WIFI_MODE_RELEASED,
    WIFI_SHIFT_PRESSED,
    WIFI_SHIFT_RELEASED,
)
from ...colors import Color
from ...utils import FontFamily, load_font, srect
from ..base.button import Button, ButtonEvents

_LETTER_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
_SYMBOL_ROWS = ["1234567890", '-/:;()&@"', ".,?!'+="]


class WifiKeyboard:
    """Key layout + mode state; produces Button widgets via :meth:`build`."""

    def __init__(self):
        self.shift = False
        self.symbols = False

    def reset(self) -> None:
        self.shift = False
        self.symbols = False

    def toggle_shift(self) -> bool:
        """Flip shift (letters mode only). Returns True when the mode changed."""
        if self.symbols:
            return False
        self.shift = not self.shift
        return True

    def toggle_mode(self) -> bool:
        """Switch letters <-> symbols. Returns True (always a change)."""
        self.symbols = not self.symbols
        self.shift = False
        return True

    def build(self) -> list[Button]:
        keys: list[Button] = []
        rows = _SYMBOL_ROWS if self.symbols else _LETTER_ROWS
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
                "",  # arrow_upward (shift)
                WIFI_SHIFT_PRESSED,
                WIFI_SHIFT_RELEASED,
                active=self.shift and not self.symbols,
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
                "",  # backspace
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
                text="ABC" if self.symbols else "123",
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
        display = ch.upper() if (self.shift and not self.symbols) else ch
        return Button(
            rect=srect(x, y, WIFI_KEY_W, WIFI_KEY_H),
            text=display,
            font=font,
            antialias=True,
            events=ButtonEvents(pressed=WIFI_KEY_PRESSED, released=WIFI_KEY_RELEASED),
            event_data={"label": display},
            text_color=Color.WHITE.rgb(),
        )

    @staticmethod
    def _special_button(x, y, w, icon, pressed_evt, released_evt, active=False) -> Button:
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
