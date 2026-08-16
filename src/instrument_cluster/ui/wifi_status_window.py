"""The Wi-Fi connecting pill — a small NOTIFICATION overlay shown while
wpa_supplicant is still associating after boot.

The dashboard is never gated on connectivity (see ``main.run``): with
credentials provisioned the app boots straight to the gauges and this pill
is the only trace of the association still running in the background. It
withdraws itself the moment the link is up and never comes back — boot
status, not a link monitor (link loss mid-session is telemetry loss, and
that is the no-telemetry alert's job).

Association is polled on a daemon thread: ``wpa_cli`` is a subprocess and
its 10-30 ms would otherwise hitch the 60 fps main loop. The thread ends
with the first successful poll.
"""

from __future__ import annotations

import threading
import time

import pygame

from ..logger import Logger
from .skins import active_skin
from .status_pill import build_pill
from .window_layering import OverlayWindow, WindowLayer

logger = Logger("wifi_status").get()

# The shared status pill (see status_pill.py), centred in the free strip
# between the widget rows — a status note, not an alert, so the border
# stays the quiet grey. When the no-telemetry alert is up its SYSTEM_ALERT
# layer occludes this window, which is exactly the right precedence.
PILL_TEXT = "Connecting to Wi-Fi ..."

# Poll fast at first — association after boot typically lands within
# seconds — then back off, so a track day with the router left off doesn't
# run wpa_cli every second for the whole session.
_POLL_FAST = 1.0
_POLL_SLOW = 5.0
_POLL_FAST_WINDOW = 30.0


def _build_pill() -> pygame.sprite.DirtySprite:
    return build_pill(PILL_TEXT, active_skin().overlays.wifi_pill_border_color)


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
        # A supplicant that raced udev at boot fails once and stays dead
        # (the template unit has no Restart=). On this provisioned-boot
        # path no scan ever runs, so unlike Wi-Fi setup nothing would
        # revive it — the device stays offline until someone opens the
        # scan screen by hand. Heal it here before settling into the
        # association poll; on a healthy boot this returns immediately.
        if not manager.ensure_supplicant():
            logger.error("Supplicant unreachable; Wi-Fi stays down this boot.")
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
