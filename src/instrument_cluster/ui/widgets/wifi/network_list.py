"""Scrollable network list for the Wi-Fi scan phase.

Styled like the settings rows (see ``SetupView``): full-width borderless
rows on the ``ListItem`` grid, hairline separators at the cell boundaries,
and the pressed-grey glow instead of a border. Up to four network rows
scroll elastically (shared :class:`Scrollbar` physics: rubber-band,
momentum, spring-back) while the manual-entry row is static — it follows
the networks while there are fewer than four and pins to the fifth cell
from then on, so the screen shows at most five rows and the scrollbar
appears at six (five networks + manual entry).

The owning view includes one instance in its widget list and forwards
events through :meth:`handle_event`; row selections surface as the usual
``WIFI_NETWORK_SELECTED`` / ``WIFI_OTHER_SELECTED`` pygame events posted
by the row Buttons.
"""

from __future__ import annotations

import pygame

from ....core.system.wifi_manager import Network
from ...colors import Color
from ...constants import SCREEN_WIDTH
from ...events import (
    WIFI_NETWORK_ROW_PRESSED,
    WIFI_NETWORK_SELECTED,
    WIFI_OTHER_ROW_PRESSED,
    WIFI_OTHER_SELECTED,
)
from ...utils import FontFamily, load_font, srect, su, sx, sy
from ..base.button import Button, ButtonEvents
from ..base.line import Line
from ..base.list_item import ListItem
from ..base.scrollbar import Scrollbar

# Row grid, derived from the settings rows so both lists share one look.
_GAP = ListItem.ROW_PITCH - ListItem.DEFAULT_HEIGHT
_CELL_TOP = ListItem.ROW_TOP - _GAP / 2  # first cell boundary (header line)
_ROW_X = ListItem.SEPARATOR_INSET
_ROW_W = SCREEN_WIDTH - 2 * ListItem.SEPARATOR_INSET
# Stretched row rect inside its cell (same clearance dance as the setup
# rows' dropdown headers, so the pressed fill never covers a separator).
_STRETCH_DY = -_GAP / 2 + ListItem.SEPARATOR_CLEARANCE
_STRETCH_H = ListItem.DEFAULT_HEIGHT + _GAP - 2 * ListItem.SEPARATOR_CLEARANCE

_VISIBLE_NETWORK_CELLS = 4


class _NetworkRows:
    """Adapter the Scrollbar dispatches forwarded taps / press-cancels to."""

    def __init__(self, owner: "WifiNetworkList"):
        self._owner = owner

    def handle_event(self, event) -> None:
        for btn in self._owner._hittable_network_buttons():
            btn.handle_event(event)


class WifiNetworkList:
    """Elastic, touch-draggable list of scan results."""

    def __init__(self):
        self._icon_font = load_font(size=30, family=FontFamily.MATERIAL_SYMBOLS)

        self._network_rows: list[tuple[Button, Network]] = []
        self._current_ssid: str = ""
        self._other_btn: Button | None = None
        self._rows_adapter = _NetworkRows(self)
        self._scrollbar = self._make_scrollbar(0)

    # ------------------------------------------------------------------
    # content
    # ------------------------------------------------------------------
    @property
    def is_empty(self) -> bool:
        return not self._network_rows

    def set_networks(self, networks: list[Network], current_ssid: str = "") -> None:
        self.reset()
        self._current_ssid = current_ssid
        self._network_rows = [
            (self._network_button(i, net), net) for i, net in enumerate(networks)
        ]
        self._other_btn = self._other_button(
            min(len(networks), _VISIBLE_NETWORK_CELLS)
        )
        self._scrollbar = self._make_scrollbar(len(networks))

    def clear(self) -> None:
        """Empty the list (scanning in progress)."""
        self.reset()
        self._network_rows = []
        self._other_btn = None
        self._scrollbar = self._make_scrollbar(0)

    def _make_scrollbar(self, network_count: int) -> Scrollbar:
        # Viewport: the four network cells, from the first row's content top
        # to the manual row's cell boundary. Content height follows the
        # ListItemGroup convention (last cell bottom minus first content
        # top), so four networks fit exactly and a fifth starts scrolling.
        viewport_height = _VISIBLE_NETWORK_CELLS * ListItem.ROW_PITCH - _GAP / 2
        content_height = (
            (network_count - 1) * ListItem.ROW_PITCH
            + ListItem.DEFAULT_HEIGHT
            + _GAP / 2
            if network_count
            else 0.0
        )
        return Scrollbar(
            viewport_top=ListItem.ROW_TOP,
            viewport_height=viewport_height,
            content_height=content_height,
            # Same breathing room above the separator as ROW_TOP leaves
            # below the header line.
            track_margin_bottom=_GAP / 2,
            # Come to rest on whole rows — never leave one half-cut under
            # the header.
            snap_interval=ListItem.ROW_PITCH,
        )

    def _cell_content_y(self, cell: int) -> float:
        return ListItem.ROW_TOP + cell * ListItem.ROW_PITCH

    def _row_button(self, cell: int, text: str, events: ButtonEvents, **kw) -> Button:
        return Button(
            rect=srect(
                _ROW_X,
                self._cell_content_y(cell) + _STRETCH_DY,
                _ROW_W,
                _STRETCH_H,
            ),
            text=text,
            text_visible=True,
            # SSIDs are arbitrary user text — NotoSans covers accents and
            # non-Latin scripts.
            font=load_font(
                size=ListItem.ROW_FONT_SIZE, family=FontFamily.NOTOSANS_REGULAR
            ),
            antialias=True,
            events=events,
            content_align="left",
            # Text on the settings rows' caption column.
            padding=(su(ListItem.LABEL_X - _ROW_X), su(20), su(20), su(20)),
            text_offset_y=su(4),
            text_color=Color.WHITE.rgb(),
            show_border=False,
            pressed_gradient=(Color.DARKER_GREY.rgb(), Color.DARKER_GREY.rgb()),
            **kw,
        )

    def _network_button(self, index: int, net: Network) -> Button:
        return self._row_button(
            cell=index,
            text=net.ssid,
            events=ButtonEvents(
                pressed=WIFI_NETWORK_ROW_PRESSED,
                released=WIFI_NETWORK_SELECTED,
            ),
            event_data={"ssid": net.ssid, "secured": net.secured},
        )

    def _other_button(self, cell: int) -> Button:
        return self._row_button(
            cell=cell,
            text="Enter network manually ...",
            events=ButtonEvents(
                pressed=WIFI_OTHER_ROW_PRESSED,
                released=WIFI_OTHER_SELECTED,
            ),
        )

    # ------------------------------------------------------------------
    # update / draw
    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        self._scrollbar.update(dt)
        offset = self._scrollbar.offset
        for i, (btn, _) in enumerate(self._network_rows):
            top = self._cell_content_y(i) + _STRETCH_DY - offset
            btn.rect.top = round(sy(top))
            btn.update(dt)
        if self._other_btn is not None:
            self._other_btn.update(dt)

    def _hittable_network_buttons(self) -> list[Button]:
        """Network rows that may receive input: all of them while the list
        fits, only the ones inside the viewport once it scrolls (rows slid
        under the header or the manual row must not swallow taps)."""
        buttons = [btn for btn, _ in self._network_rows]
        if not self._scrollbar.is_scrollable:
            return buttons
        viewport = self._scrollbar.viewport_rect()
        return [btn for btn in buttons if btn.rect.colliderect(viewport)]

    def draw(self, surface) -> None:
        scrollable = self._scrollbar.is_scrollable
        offset = self._scrollbar.offset

        if scrollable:
            prev_clip = surface.get_clip()
            surface.set_clip(self._scrollbar.viewport_rect())

        for btn, _ in self._network_rows:
            surface.blit(btn.image, btn.rect)
        self._draw_decorations(surface)
        # Separators between network rows, at the cell boundaries.
        for i in range(1, len(self._network_rows)):
            self._draw_separator(surface, _CELL_TOP + i * ListItem.ROW_PITCH - offset)

        if scrollable:
            surface.set_clip(prev_clip)

        if self._other_btn is not None:
            # The manual row is static: its separator does not scroll.
            if self._network_rows:
                boundary = self._other_btn_cell_boundary()
                self._draw_separator(surface, boundary)
            surface.blit(self._other_btn.image, self._other_btn.rect)

        self._scrollbar.draw(surface)

    def _other_btn_cell_boundary(self) -> float:
        cells = min(len(self._network_rows), _VISIBLE_NETWORK_CELLS)
        return _CELL_TOP + cells * ListItem.ROW_PITCH

    def _draw_separator(self, surface, y: float) -> None:
        Line(
            start_pos=(ListItem.SEPARATOR_INSET, y),
            length=SCREEN_WIDTH - 2 * ListItem.SEPARATOR_INSET,
            color=ListItem.SEPARATOR_COLOR,
            width=ListItem.SEPARATOR_WIDTH,
        ).draw(surface)

    def _draw_decorations(self, surface) -> None:
        for button, net in self._network_rows:
            self._draw_signal_bars(surface, button.rect, net.bars)
            if self._current_ssid and net.ssid == self._current_ssid:
                check = self._icon_font.render("", True, Color.LIGHT_GREEN.rgb())
                r = check.get_rect()
                r.right = button.rect.right - sx(108)
                r.centery = button.rect.centery
                surface.blit(check, r)
            if net.secured:
                lock = self._icon_font.render("", True, Color.WHITE.rgb())
                r = lock.get_rect()
                r.right = button.rect.right - sx(72)
                r.centery = button.rect.centery
                surface.blit(lock, r)

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

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Cancel any in-flight gesture and drop the scroll position."""
        self._scrollbar = self._make_scrollbar(len(self._network_rows))

    def handle_event(self, event) -> bool:
        """Dispatch an event to the list.

        The elastic Scrollbar gets first crack: it owns the tap-vs-drag
        disambiguation over the network rows and consumes the whole gesture
        when it takes it (the caller must not dispatch further). Otherwise
        the rows see the event directly (mouse input on dev machines, taps
        while the list doesn't scroll) and the caller continues as usual.
        """
        if self._scrollbar.handle_event(event, self._rows_adapter):
            return True
        for btn in self._hittable_network_buttons():
            btn.handle_event(event)
        if self._other_btn is not None:
            self._other_btn.handle_event(event)
        return False
