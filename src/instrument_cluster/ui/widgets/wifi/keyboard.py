"""On-screen QWERTY keyboard for the Wi-Fi password phase.

Owns the shift/symbols mode state and builds the key Button widgets for
the current mode. The owning view calls :meth:`build` whenever it
rebuilds its widget list; the toggle methods report whether the mode
actually changed so the caller knows a rebuild is needed.
"""

from __future__ import annotations

from ...colors import Color
from ...icons import Icon
from ...events import (
    WIFI_CONNECT_PRESSED,
    WIFI_CONNECT_RELEASED,
    WIFI_KEY_PRESSED,
    WIFI_KEY_RELEASED,
    WIFI_MODE_PRESSED,
    WIFI_MODE_RELEASED,
    WIFI_REVEAL_PRESSED,
    WIFI_REVEAL_RELEASED,
    WIFI_SHIFT_PRESSED,
    WIFI_SHIFT_RELEASED,
)
from ...skins import active_skin
from ...utils import FontFamily, load_font_px
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
        skin = active_skin()
        kb = skin.keyboard
        key_font = load_font_px(kb.key_font, FontFamily[kb.key_font_family])

        # First two rows: plain character keys, centered.
        for r in range(2):
            keys.extend(
                self._char_row(rows[r], kb.top + r * kb.row_step, key_font)
            )

        # Third row: shift + chars + password-reveal (backspace moved
        # up beside the password field).
        y2 = kb.top + 2 * kb.row_step
        chars = rows[2]
        block_w = len(chars) * kb.key_w + (len(chars) - 1) * kb.gap
        total = kb.special_w + kb.gap + block_w + kb.gap + kb.special_w
        x = (skin.width - total) / 2
        keys.append(
            self._special_button(
                x,
                y2,
                kb.special_w,
                Icon.SHIFT.glyph(),
                WIFI_SHIFT_PRESSED,
                WIFI_SHIFT_RELEASED,
                active=self.shift and not self.symbols,
            )
        )
        x += kb.special_w + kb.gap
        for ch in chars:
            keys.append(self._char_key(x, y2, ch, key_font))
            x += kb.key_w + kb.gap
        keys.append(
            self._special_button(
                x,
                y2,
                kb.special_w,
                Icon.REVEAL.glyph(),
                WIFI_REVEAL_PRESSED,
                WIFI_REVEAL_RELEASED,
            )
        )

        # Fourth row: mode toggle + space + connect.
        y3 = kb.top + 3 * kb.row_step
        total = kb.special_w + kb.gap + kb.space_w + kb.gap + kb.special_w
        x = (skin.width - total) / 2
        keys.append(
            Button(
                rect=self._key_rect(x, y3, kb.special_w, kb.key_h),
                text="ABC" if self.symbols else "123",
                font=load_font_px(
                    kb.small_font, FontFamily[kb.small_font_family]
                ),
                antialias=True,
                events=ButtonEvents(
                    pressed=WIFI_MODE_PRESSED, released=WIFI_MODE_RELEASED
                ),
                text_color=Color.WHITE.rgb(),
            )
        )
        x += kb.special_w + kb.gap
        keys.append(
            Button(
                rect=self._key_rect(x, y3, kb.space_w, kb.key_h),
                text="space",
                font=load_font_px(
                    kb.small_font, FontFamily[kb.small_font_family]
                ),
                antialias=True,
                events=ButtonEvents(
                    pressed=WIFI_KEY_PRESSED, released=WIFI_KEY_RELEASED
                ),
                event_data={"label": " "},
                text_color=Color.LIGHT_GREY.rgb(),
            )
        )
        x += kb.space_w + kb.gap
        keys.append(
            Button(
                rect=self._key_rect(x, y3, kb.special_w, kb.key_h),
                text="OK",
                font=load_font_px(kb.key_font, FontFamily[kb.key_font_family]),
                antialias=True,
                events=ButtonEvents(
                    pressed=WIFI_CONNECT_PRESSED, released=WIFI_CONNECT_RELEASED
                ),
                text_color=Color[kb.ok_color].rgb(),
                pressed_gradient=(Color.DARK_GREEN.rgb(), Color.BLACK.rgb()),
            )
        )
        return keys

    @staticmethod
    def _key_rect(x: float, y: float, w: float, h: float):
        return (round(x), round(y), round(w), round(h))

    def _char_row(self, chars: str, y: float, font) -> list[Button]:
        skin = active_skin()
        kb = skin.keyboard
        block_w = len(chars) * kb.key_w + (len(chars) - 1) * kb.gap
        x = (skin.width - block_w) / 2
        out = []
        for ch in chars:
            out.append(self._char_key(x, y, ch, font))
            x += kb.key_w + kb.gap
        return out

    def _char_key(self, x: float, y: float, ch: str, font) -> Button:
        kb = active_skin().keyboard
        display = ch.upper() if (self.shift and not self.symbols) else ch
        return Button(
            rect=self._key_rect(x, y, kb.key_w, kb.key_h),
            text=display,
            font=font,
            antialias=True,
            events=ButtonEvents(pressed=WIFI_KEY_PRESSED, released=WIFI_KEY_RELEASED),
            event_data={"label": display},
            text_color=Color[kb.key_text_color].rgb(),
        )

    @staticmethod
    def _special_button(
        x, y, w, icon, pressed_evt, released_evt, active=False
    ) -> Button:
        kb = active_skin().keyboard
        return Button(
            rect=WifiKeyboard._key_rect(x, y, w, kb.key_h),
            text="",
            text_visible=False,
            font=load_font_px(kb.key_font, FontFamily[kb.key_font_family]),
            antialias=True,
            events=ButtonEvents(pressed=pressed_evt, released=released_evt),
            icon=icon,
            icon_size=kb.key_font,
            icon_font=load_font_px(kb.key_font, FontFamily.MATERIAL_SYMBOLS),
            icon_position="center",
            icon_color=Color.BLUE.rgb() if active else Color.WHITE.rgb(),
        )
