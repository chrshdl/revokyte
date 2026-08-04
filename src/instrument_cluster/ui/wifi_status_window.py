"""The Wi-Fi connecting pill — a small NOTIFICATION overlay shown while
wpa_supplicant is still associating after boot.

The dashboard is never gated on connectivity (see ``main.run``): with
credentials provisioned the app boots straight to the gauges and this pill
is the only trace of the association still running in the background. It
withdraws itself the moment the link is up and never comes back — boot
status, not a link monitor (link loss mid-session is telemetry loss, and
that is the NO SIGNAL band's job).

Association is polled on a daemon thread: ``wpa_cli`` is a subprocess and
its 10-30 ms would otherwise hitch the 60 fps main loop. The thread ends
with the first successful poll.
"""

from __future__ import annotations

import threading
import time

import pygame

from ..logger import Logger
from ..peripherals.display import DESIGN_WIDTH
from .colors import Color
from .utils import FontFamily, load_font, su, sx, sy
from .window_layering import OverlayWindow, WindowLayer

logger = Logger("wifi_status").get()

# Geometry, in design px. Centred in the same free strip between the widget
# rows that the NO SIGNAL band occupies (see no_signal_window.py for why
# that strip) — but a compact pill, not a full-width band: this is a status
# note, not an alert. When NO SIGNAL is up its SYSTEM_ALERT layer occludes
# this window, which is exactly the right precedence.
PILL_HEIGHT = 56
PILL_CENTER_Y = 564
PILL_PAD_X = 28
PILL_TEXT = "Connecting to Wi-Fi …"
PILL_FONT_SIZE = 26
PILL_FONT_FAMILY = FontFamily.D_DIN

PILL_BG_COLOR = (*Color.DARKER_GREY.rgb(), 235)
PILL_BORDER_COLOR = Color.MID_GREY.rgb()
PILL_BORDER_WIDTH = 2
PILL_TEXT_COLOR = Color.WHITE.rgb()

# Poll fast at first — association after boot typically lands within
# seconds — then back off, so a track day with the router left off doesn't
# run wpa_cli every second for the whole session.
_POLL_FAST = 1.0
_POLL_SLOW = 5.0
_POLL_FAST_WINDOW = 30.0


def _build_pill() -> pygame.sprite.DirtySprite:
    font = load_font(size=PILL_FONT_SIZE, family=PILL_FONT_FAMILY)
    text = font.render(PILL_TEXT, True, PILL_TEXT_COLOR)

    width = text.get_width() + 2 * su(PILL_PAD_X)
    height = sy(PILL_HEIGHT)
    radius = height // 2

    image = pygame.Surface((width, height), pygame.SRCALPHA)
    pygame.draw.rect(image, PILL_BG_COLOR, image.get_rect(), border_radius=radius)
    pygame.draw.rect(
        image,
        PILL_BORDER_COLOR,
        image.get_rect(),
        width=max(1, su(PILL_BORDER_WIDTH)),
        border_radius=radius,
    )
    image.blit(text, text.get_rect(center=image.get_rect().center))

    sprite = pygame.sprite.DirtySprite()
    sprite.image = image
    sprite.rect = image.get_rect(
        center=(sx(DESIGN_WIDTH) // 2, sy(PILL_CENTER_Y))
    )
    sprite.visible = 1
    sprite.dirty = 1
    return sprite


class WifiStatusWindow(OverlayWindow):
    """Shows the connecting pill until wpa_supplicant associates."""

    layer = WindowLayer.NOTIFICATION

    def __init__(self, manager, state_manager):
        super().__init__()
        self._state_manager = state_manager
        self._done = threading.Event()
        self._was_showing = False

        # Resolved once, now: on dev machines (no wlan0) or when the link is
        # already up there is nothing to say — no sprite, no poller, and
        # `visible` stays False for the life of the process.
        if not (manager.available and not manager.is_associated()):
            self._done.set()
            return

        self.sprites = [_build_pill()]
        threading.Thread(
            target=self._poll, args=(manager,), name="wifi-status-poller", daemon=True
        ).start()

    def _poll(self, manager) -> None:
        fast_until = time.monotonic() + _POLL_FAST_WINDOW
        while not self._done.is_set():
            if manager.is_associated():
                logger.info("Wi-Fi associated.")
                self._done.set()
                return
            time.sleep(_POLL_FAST if time.monotonic() < fast_until else _POLL_SLOW)

    @property
    def visible(self) -> bool:
        if self._done.is_set():
            return False
        # Only over the dashboard — the same duck-typed opt-in the system
        # alert uses. Setup and settings screens either manage Wi-Fi
        # themselves or would be covered mid-interaction.
        state = self._state_manager.current_state
        return bool(getattr(state, "allows_system_alert", False))

    def update(self, dt: float) -> None:
        # The pill image never changes, so its sprite stays clean after the
        # first paint and a reappearance (e.g. after NO SIGNAL withdrew it,
        # or coming back from Setup) would composite nothing. Re-dirty on
        # the rising edge of actually being up.
        now = self.showing
        if now and not self._was_showing:
            for sprite in self.sprites:
                sprite.dirty = 1
        self._was_showing = now
