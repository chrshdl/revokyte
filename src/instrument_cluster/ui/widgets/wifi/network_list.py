"""Scrollable network list for the Wi-Fi scan phase.

A self-contained widget: owns the network rows (plus the manual-entry
row), the signal-bar / lock / connected decorations, the scrollbar, and
the tap-vs-drag gesture disambiguation. The owning view includes one
instance in its widget list and forwards events through
:meth:`handle_event`; row selections surface as the usual
``WIFI_NETWORK_SELECTED`` / ``WIFI_OTHER_SELECTED`` pygame events posted
by the row Buttons.
"""

from __future__ import annotations

import pygame

from ....core.system.wifi_manager import Network
from ....peripherals.display import active_profile
from ...colors import Color
from ...constants import (
    SCREEN_WIDTH,
    WIFI_LIST_TOP,
    WIFI_LIST_X,
    WIFI_MAX_ROWS,
    WIFI_ROW_GAP,
    WIFI_ROW_HEIGHT,
    WIFI_ROW_WIDTH,
)
from ...events import (
    WIFI_NETWORK_ROW_PRESSED,
    WIFI_NETWORK_SELECTED,
    WIFI_OTHER_ROW_PRESSED,
    WIFI_OTHER_SELECTED,
)
from ...utils import FontFamily, load_font, srect, su, sx, sy
from ..base.button import Button, ButtonEvents


class WifiNetworkList:
    """Scrollable, touch-draggable list of scan results."""

    # scrollbar geometry (design-space px)
    _SB_W = 8  # visual bar width
    _SB_RIGHT = 16  # margin between bar right and screen right edge
    _SB_PAD = 20  # gap between row content and bar (clears hit zone)
    _SB_MIN_THUMB = 32  # minimum thumb height
    _DRAG_THRESHOLD = 15  # design-px movement before a touch becomes a drag

    def __init__(self):
        self._icon_font = load_font(size=30, family=FontFamily.MATERIAL_SYMBOLS)

        # rows kept for manual signal-bar / lock rendering
        self._network_rows: list[tuple[Button, Network]] = []
        self._all_networks: list[Network] = []
        self._scroll_offset: int = 0
        self._other_btn: Button | None = None
        self._current_ssid: str = ""

        # tap/drag disambiguation state
        self._gesture_id: int | None = None
        self._gesture_start: tuple[float, float] | None = None
        self._gesture_drag: bool = False
        self._gesture_scroll_base: int = 0

        # scrollbar drag state
        self._sb_dragging: bool = False
        self._sb_finger_id: int | None = None

    # ------------------------------------------------------------------
    # content
    # ------------------------------------------------------------------
    @property
    def is_empty(self) -> bool:
        return not self._all_networks

    def set_networks(self, networks: list[Network], current_ssid: str = "") -> None:
        self.reset()
        self._all_networks = networks
        self._current_ssid = current_ssid
        self._scroll_offset = 0
        self._rebuild_rows()

    def clear(self) -> None:
        """Empty the list (scanning in progress)."""
        self.reset()
        self._network_rows = []
        self._all_networks = []
        self._other_btn = None

    @property
    def _scrollable(self) -> bool:
        return len(self._all_networks) > WIFI_MAX_ROWS

    def _rebuild_rows(self) -> None:
        row_w = (
            SCREEN_WIDTH - WIFI_LIST_X - self._SB_W - self._SB_RIGHT - self._SB_PAD
            if self._scrollable
            else WIFI_ROW_WIDTH
        )
        self._network_rows = []
        y = WIFI_LIST_TOP
        window = self._all_networks[
            self._scroll_offset : self._scroll_offset + WIFI_MAX_ROWS
        ]
        for net in window:
            self._network_rows.append((self._network_button(y, net, row_w), net))
            y += WIFI_ROW_HEIGHT + WIFI_ROW_GAP
        self._other_btn = self._other_button(y, row_w)

    def _network_button(self, y: float, net: Network, width: int) -> Button:
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

    def _other_button(self, y: float, width: int) -> Button:
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

    def _buttons(self) -> list[Button]:
        out = [btn for btn, _ in self._network_rows]
        if self._other_btn is not None:
            out.append(self._other_btn)
        return out

    # ------------------------------------------------------------------
    # update / draw
    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        for btn in self._buttons():
            btn.update(dt)

    def draw(self, surface) -> None:
        for btn in self._buttons():
            if getattr(btn, "visible", True):
                surface.blit(btn.image, btn.rect)
        self._draw_decorations(surface)
        if self._scrollable:
            self._draw_scrollbar(surface)

    def _draw_decorations(self, surface) -> None:
        for button, net in self._network_rows:
            self._draw_signal_bars(surface, button.rect, net.bars)
            if self._current_ssid and net.ssid == self._current_ssid:
                check = self._icon_font.render("", True, Color.LIGHT_GREEN.rgb())
                r = check.get_rect()
                r.right = button.rect.right - sx(108)
                r.centery = button.rect.centery
                surface.blit(check, r)
            if net.secured:
                lock = self._icon_font.render("", True, Color.WHITE.rgb())
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

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Cancel any active gesture or scrollbar drag and clear tracking state."""
        if self._gesture_id is not None:
            self._cancel_gesture_press()
        self._gesture_id = None
        self._gesture_start = None
        self._gesture_drag = False
        self._gesture_scroll_base = 0
        self._sb_dragging = False
        self._sb_finger_id = None

    def handle_event(self, event) -> bool:
        """Dispatch an event to the list.

        Returns True when the event was consumed by the tap/drag gesture
        machinery (the caller must not dispatch it further); otherwise the
        rows have seen the event (mouse input on dev machines) and the
        scrollbar had its chance, and the caller continues as usual.
        """
        if self._intercept_touch(event):
            return True
        for btn in self._buttons():
            btn.handle_event(event)
        self._handle_scrollbar(event)
        return False

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
        for btn in self._buttons():
            btn.handle_event(cancel)

    def _intercept_touch(self, event) -> bool:
        """Disambiguate list taps from drag gestures.

        On FINGERDOWN, the event is forwarded to the rows immediately so the
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
            # Only intercept touches that land on a row button.
            hit = next(
                (btn for btn in self._buttons() if btn.rect.collidepoint(lx, ly)),
                None,
            )
            if hit is None:
                return False
            # Forward FINGERDOWN now: button goes PRESSED (blue highlight).
            # Because pressed=WIFI_NETWORK_ROW_PRESSED (no handler), the
            # selection action does NOT fire yet.
            for btn in self._buttons():
                btn.handle_event(event)
            self._gesture_id = event.finger_id
            self._gesture_start = (lx, ly)
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
                if self._gesture_drag and self._scrollable:
                    row_h = sy(WIFI_ROW_HEIGHT + WIFI_ROW_GAP)
                    steps = -round(dy / row_h)
                    max_offset = len(self._all_networks) - WIFI_MAX_ROWS
                    new_off = max(0, min(max_offset, self._gesture_scroll_base + steps))
                    if new_off != self._scroll_offset:
                        self._scroll_offset = new_off
                        self._rebuild_rows()
            return True

        if event.type == pygame.FINGERUP:
            if event.finger_id != self._gesture_id:
                return False
            if not self._gesture_drag:
                # Confirmed tap: deliver FINGERUP so released fires the
                # row's selected event.
                for btn in self._buttons():
                    btn.handle_event(event)
            # else: drag — list already scrolled during FINGERMOTION.
            self._gesture_id = None
            self._gesture_start = None
            self._gesture_drag = False
            self._gesture_scroll_base = 0
            return True

        return False

    def _handle_scrollbar(self, event) -> None:
        """Direct scrollbar navigation (tap or drag on the track)."""
        if not self._scrollable:
            return

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
                    self._rebuild_rows()

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
                        self._rebuild_rows()

        elif (
            event.type in (pygame.FINGERUP, pygame.MOUSEBUTTONUP)
            and self._sb_dragging
        ):
            if getattr(event, "finger_id", 0) == self._sb_finger_id:
                self._sb_dragging = False
                self._sb_finger_id = None
