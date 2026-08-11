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
from ...icons import Icon
from ...events import (
    WIFI_NETWORK_ROW_PRESSED,
    WIFI_NETWORK_SELECTED,
    WIFI_OTHER_ROW_PRESSED,
    WIFI_OTHER_SELECTED,
)
from ...skins import active_skin
from ...utils import FontFamily, load_font, load_font_px, su, sx, sy
from ..base.button import Button, ButtonEvents
from ..base.line import Line
from ..base.list_item import ListItem
from ..base.scrollbar import Scrollbar

class _Grid:
    """Row grid in native px, derived from the active skin's settings rows
    so both lists share one look. Resolved at construction time (never at
    import) because the skin follows the display profile."""

    def __init__(self):
        skin = active_skin()
        s = skin.setup
        self.gap = s.row_pitch - s.row_height
        self.cell_top = s.row_top - self.gap / 2  # first cell boundary
        self.row_x = s.separator_inset
        self.row_w = skin.width - 2 * s.separator_inset
        # Stretched row rect inside its cell (same clearance dance as the
        # setup rows' dropdown headers, so the pressed fill never covers a
        # separator).
        self.stretch_dy = -self.gap / 2 + s.separator_clearance
        self.stretch_h = s.row_height + self.gap - 2 * s.separator_clearance
        self.row_top = s.row_top
        self.row_pitch = s.row_pitch
        self.row_height = s.row_height
        self.label_x = s.label_x
        self.row_font_size = s.row_font_size
        self.row_font_family = s.row_font_family
        self.visible_cells = s.visible_network_cells


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
        self._grid = _Grid()
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
            min(len(networks), self._grid.visible_cells)
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
        g = self._grid
        viewport_height = g.visible_cells * g.row_pitch - g.gap / 2
        content_height = (
            (network_count - 1) * g.row_pitch + g.row_height + g.gap / 2
            if network_count
            else 0.0
        )
        return Scrollbar(
            viewport_top=g.row_top,
            viewport_height=viewport_height,
            content_height=content_height,
            # Same breathing room above the separator as row_top leaves
            # below the header line.
            track_margin_bottom=g.gap / 2,
            # Come to rest on whole rows — never leave one half-cut under
            # the header.
            snap_interval=g.row_pitch,
        )

    def _cell_content_y(self, cell: int) -> float:
        return self._grid.row_top + cell * self._grid.row_pitch

    def _row_button(self, cell: int, text: str, events: ButtonEvents, **kw) -> Button:
        g = self._grid
        return Button(
            rect=(
                g.row_x,
                round(self._cell_content_y(cell) + g.stretch_dy),
                g.row_w,
                round(g.stretch_h),
            ),
            text=text,
            text_visible=True,
            # SSIDs are arbitrary user text — NotoSans covers accents and
            # non-Latin scripts.
            font=load_font_px(
                g.row_font_size, FontFamily[g.row_font_family]
            ),
            antialias=True,
            events=events,
            content_align="left",
            # Text on the settings rows' caption column.
            padding=(g.label_x - g.row_x, su(20), su(20), su(20)),
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
            top = self._cell_content_y(i) + self._grid.stretch_dy - offset
            btn.rect.top = round(top)
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
        g = self._grid
        for i in range(1, len(self._network_rows)):
            self._draw_separator(
                surface, g.cell_top + i * g.row_pitch - offset
            )

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
        g = self._grid
        cells = min(len(self._network_rows), g.visible_cells)
        return g.cell_top + cells * g.row_pitch

    def _draw_separator(self, surface, y: float) -> None:
        skin = active_skin()
        inset = skin.setup.separator_inset
        Line(
            start_pos=(inset, y),
            length=skin.width - 2 * inset,
            color=ListItem.separator_color(),
            width=skin.setup.separator_width,
        ).draw(surface)

    def _draw_decorations(self, surface) -> None:
        for button, net in self._network_rows:
            self._draw_signal_bars(surface, button.rect, net.bars)
            if self._current_ssid and net.ssid == self._current_ssid:
                check = self._icon_font.render(
                    Icon.ROW_CHECK.glyph(), True, Color.LIGHT_GREEN.rgb()
                )
                r = check.get_rect()
                r.right = button.rect.right - sx(108)
                r.centery = button.rect.centery
                surface.blit(check, r)
            if net.secured:
                lock = self._icon_font.render(
                    Icon.LOCK.glyph(), True, Color.WHITE.rgb()
                )
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
