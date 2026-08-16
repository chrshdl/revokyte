"""The no-telemetry alert — a composited SYSTEM_ALERT overlay window.

Telemetry link loss is exactly what the topmost overlay layer is for. Making
it a window rather than something ``DashboardView`` paints buys two things
the view could not give it:

* nothing can draw over it. A widget repainting under the pill is
  re-composited beneath it by the WindowManager, instead of the view having
  to restamp it whenever a dirty rect wandered into it;
* the base keeps running live underneath, and the compositor already knows
  to repaint the base when the window disappears — so clearing the alert on
  recovery is no longer the view's problem either.

The alert renders as the shared status pill (see ``status_pill.py``) — the
same compact pill the Wi-Fi connecting note uses, centred in the free strip
between the widget rows, in the same quiet colours. A full-width gradient
band was tried and dropped, and so was a red accent border: against the
Wi-Fi pill both read as a second design language, and the strip's job is
glance-legibility, which the pill already delivers. The wording alone
carries the alert.

Visibility is driven by ``LinkSignal``'s ``telemetry_stale`` (see
``signals/link_signal.py``), gated on the active state opting in, the same
way notification popups are.
"""

from __future__ import annotations

import pygame

from ..signals.signal_keys import SignalKey
from .skins import active_skin
from .status_pill import build_pill
from .window_layering import OverlayWindow, WindowLayer

# The wording carries the diagnosis: "No Telemetry" names what is missing
# (the feed), where "no signal" read like a display/input problem. The
# trailing dots read as an ongoing wait, not a verdict.
PILL_TEXT = "No Telemetry ..."


def build_no_telemetry_pill() -> pygame.sprite.DirtySprite:
    """The alert pill: the shared shape and colours, alert wording."""
    return build_pill(PILL_TEXT, active_skin().overlays.wifi_pill_border_color)


class NoSignalWindow(OverlayWindow):
    """Shows the no-telemetry pill while the telemetry link is dead."""

    layer = WindowLayer.SYSTEM_ALERT
    # A dead link is read alone: a notification card sharing the screen
    # competes for the same glance, and the card's own 35% dimming knocks
    # back the very gauges this alert marks as stale. The card is withdrawn
    # while this is up and returns on recovery, so nothing is lost by making
    # it wait. The remedy stays reachable meanwhile: the pill clears the
    # footer, so the Setup button — and its "Telemetry (update)" row — is
    # still there.
    occludes_below = True

    def __init__(self, vehicle_bus, state_manager):
        super().__init__()
        self._bus = vehicle_bus
        self._state_manager = state_manager

        self.sprites = [build_no_telemetry_pill()]
        self._was_showing = False

    @property
    def visible(self) -> bool:
        if not self._bus.signals.get(SignalKey.TELEMETRY_STALE):
            return False
        # Only over the dashboard. Covering Setup — where the feed is
        # configured, i.e. where someone goes to *fix* a dead link — would
        # obscure the remedy. Same duck-typed opt-in as notification popups.
        state = self._state_manager.current_state
        return bool(getattr(state, "allows_system_alert", False))

    def update(self, dt: float) -> None:
        # The pill image never changes, so its sprite would stay clean
        # after the first paint and a later reappearance would composite
        # nothing. Re-dirty it on the rising edge of actually being up —
        # `showing`, not `visible`, or a window that was withdrawn by
        # arbitration while stale would come back invisible.
        now = self.showing
        if now and not self._was_showing:
            for sprite in self.sprites:
                sprite.dirty = 1
        self._was_showing = now
