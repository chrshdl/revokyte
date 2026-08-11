"""The "telemetry feed is out of date" notice — a NOTIFICATION overlay window.

The feed install lives on ``/data`` and survives OS updates, so a device can
keep running a build the current image was never tested against (see
``feeds.feed_needs_reinstall``). The Setup row flags it, but that only helps
someone already looking; on a release image the log line helps nobody, since
there is no SSH. This is the half that goes and finds the driver.

Its single **Update now** button performs the re-install rather than telling
the driver where to find it — the notice already knows the feed and the
console address, so sending someone to Setup to re-pick the game would be
busywork. There is deliberately no way to decline: a feed the image was never
tested against is not a state to leave a device sitting in, and updating is
the whole point of the notice. (The install screen it opens has its own
Cancel, so nobody is trapped.)
"""

from __future__ import annotations

import pygame

from ..addons.feeds import FeedDescriptor, feed_needs_reinstall
from ..telemetry.mode import TelemetryMode
from .colors import Color
from .events import FEED_UPDATE_NOW_PRESSED, FEED_UPDATE_NOW_RELEASED
from .skins import active_skin
from .utils import FontFamily, load_font_px
from .widgets.base.button import Button, ButtonEvents, ButtonGroup
from .widgets.base.modal_dimming import ModalDimming
from .window_layering import OverlayWindow, WindowLayer

# How far the live dashboard is knocked back behind the card.
DIM_PERCENT = 35.0

# Card geometry comes from the active skin's overlays group (centred).
CARD_BORDER_WIDTH = 2


def _card_color() -> tuple:
    """The card's fill, shared with the buttons so they paint opaquely
    over it. Resolved per build so palette overrides (skin editor) reach
    a rebuilt card."""
    return Color.DARKER_GREY.rgb()

TITLE_TEXT = "Telemetry feed out of date"


def _card_rect() -> pygame.Rect:
    skin = active_skin()
    w, h = skin.overlays.feed_card_size
    return pygame.Rect((skin.width - w) // 2, (skin.height - h) // 2, w, h)


def body_lines(descriptor: FeedDescriptor, installed_version: str) -> list[str]:
    """What the driver is told, in plain terms.

    Names both builds so the message is actionable rather than just alarming
    — and says "an unknown build" rather than inventing a version when the
    feed predates the version being recorded.
    """
    installed = (
        f"version {installed_version}" if installed_version else "an unknown build"
    )
    return [
        f"{descriptor.label} has {installed} installed,",
        f"but this system expects {descriptor.version}.",
    ]


def build_card(descriptor: FeedDescriptor, installed_version: str) -> pygame.Surface:
    """Render the notice card."""
    o = active_skin().overlays
    rect = _card_rect()
    card = pygame.Surface(rect.size, pygame.SRCALPHA)
    radius = max(1, o.feed_card_radius)

    pygame.draw.rect(
        card, _card_color(), card.get_rect(), border_radius=radius
    )
    accent = Color[o.feed_accent_color].rgb()
    pygame.draw.rect(
        card,
        accent,
        card.get_rect(),
        CARD_BORDER_WIDTH,
        border_radius=radius,
    )

    centre_x = rect.width // 2

    title_font = load_font_px(
        o.feed_title_font, FontFamily[o.feed_title_font_family]
    )
    title = title_font.render(TITLE_TEXT, True, accent)
    card.blit(title, title.get_rect(midtop=(centre_x, o.feed_title_top)))

    body_font = load_font_px(
        o.feed_body_font, FontFamily[o.feed_body_font_family]
    )
    y = o.feed_body_top
    for line in body_lines(descriptor, installed_version):
        if line:
            surf = body_font.render(line, True, Color.WHITE.rgb())
            card.blit(surf, surf.get_rect(midtop=(centre_x, y)))
        y += o.feed_body_line_pitch

    return card


def _button_rect() -> tuple:
    """Screen-space rect for the Update now button, centred on the card
    above its bottom edge."""
    skin = active_skin()
    o = skin.overlays
    width, height = o.feed_button_size
    card_bottom = (skin.height + o.feed_card_size[1]) // 2
    return (
        (skin.width - width) // 2,
        card_bottom - height - o.feed_button_bottom_margin,
        width,
        height,
    )


class FeedUpdateWindow(OverlayWindow):
    """Tells the driver once per boot that the installed feed is stale, and
    offers to fix it."""

    layer = WindowLayer.NOTIFICATION

    def __init__(self, config, state_manager, screen_size: tuple[int, int]):
        super().__init__()
        self._state_manager = state_manager
        self._dismissed = False
        self._was_showing = False
        self._buttons = ButtonGroup()

        descriptor = feed_needs_reinstall(
            config.telemetry_feed, config.telemetry_feed_version
        )
        # Demo mode runs no installed feed, so there is nothing to be stale.
        # Evaluated once, at construction: "once per boot" is exactly this.
        self._descriptor = (
            descriptor
            if descriptor is not None
            and config.telemetry_mode != TelemetryMode.DEMO.value
            else None
        )

        if self._descriptor is None:
            return

        dimming = ModalDimming(screen_size, percent=DIM_PERCENT)

        card = pygame.sprite.DirtySprite()
        card.image = build_card(self._descriptor, config.telemetry_feed_version)
        card.rect = _card_rect()
        card.visible = 1
        card.dirty = 1

        self.update_button = self._make_button(
            _button_rect(),
            "Update now",
            FEED_UPDATE_NOW_PRESSED,
            FEED_UPDATE_NOW_RELEASED,
        )
        self._buttons.add(self.update_button)

        # Bottom-to-top: dimming, card, then the button sitting on the card.
        self.sprites = [dimming, card, self.update_button]

    @staticmethod
    def _make_button(rect, text: str, pressed, released) -> Button:
        """Styled like InstallView's Cancel/Install pair.

        With one difference: an explicit ``bg_color``. Buttons default to a
        transparent fill and rely on their view restoring the background
        under them (``LayeredDirty.clear``) when they repaint. An overlay
        window has no background to restore — the compositor re-blits the
        sprite stack from the changed sprite upwards — so a transparent
        button would leave its own previous pressed-blue showing through
        after the press cleared. Painting the card's colour makes it
        self-contained.
        """
        return Button(
            rect=rect,
            text=text,
            text_visible=True,
            font=load_font_px(
                active_skin().overlays.feed_button_font,
                FontFamily[active_skin().overlays.feed_button_font_family],
            ),
            antialias=True,
            bg_color=_card_color(),
            events=ButtonEvents(pressed=pressed, released=released),
        )

    @property
    def visible(self) -> bool:
        if self._descriptor is None or self._dismissed:
            return False
        # Only over the dashboard — the same duck-typed opt-in the extension
        # popups use. Setup is where this gets fixed; covering it would be
        # backwards.
        state = self._state_manager.current_state
        return bool(getattr(state, "allows_notification_popup", False))

    def dismiss(self) -> None:
        self._dismissed = True

    def start_update(self) -> None:
        """Run the re-install, asking for nothing.

        Everything needed is already on the device: which feed, and the
        console address the installed proxy is configured with. Re-entering
        an IP would be asking the user to retype something the machine is
        currently using, and a second Install press would be confirming a
        choice already made — so the install screen is opened already
        running, purely to report progress and failures.

        Only a device with no recoverable address at all falls back to
        asking, which in practice means a feed installed before the address
        was ever recorded.
        """
        from ..addons.installer import installed_feed_ip
        from ..config import ConfigManager
        from ..states.enter_ip_state import EnterIPState
        from ..states.install_state import InstallState

        self.dismiss()

        config = ConfigManager.get_config()
        recent = list(config.recent_connected or [])
        # The env file first: it is what the running proxy actually uses,
        # where recent_connected is only what was last typed.
        ip = installed_feed_ip() or (recent[0] if recent else "")

        if ip:
            self._state_manager.push_state(
                InstallState(
                    self._state_manager,
                    descriptor=self._descriptor,
                    ip=ip,
                    auto_start=True,
                )
            )
        else:
            self._state_manager.push_state(
                EnterIPState(
                    self._state_manager,
                    descriptor=self._descriptor,
                    recent_connected=recent,
                )
            )

    def update(self, dt: float) -> None:
        # The card and the dimming never change, so their sprites go clean
        # after the first composite and a later reappearance would paint
        # nothing. Re-dirty on the rising edge of being up — the window is
        # built before the dashboard is pushed, so the very first show is
        # already such a transition, and so is returning from behind a
        # NO SIGNAL alert that withdrew it (`showing`, not `visible`).
        now = self.showing
        if now and not self._was_showing:
            for sprite in self.sprites:
                sprite.dirty = 1
        self._was_showing = now

    def handle_event(self, event) -> bool:
        # `showing`: a card withdrawn behind an alert must stop swallowing
        # touches. The WindowManager already skips occluded windows, so this
        # is the same answer from the other side.
        if not self.showing:
            return False

        # Buttons first: they own the press/release animation and post the
        # action events handled below.
        self._buttons.handle_event(event)

        if event.type == FEED_UPDATE_NOW_RELEASED:
            self.start_update()
            return True

        # Modal while it is up: swallow pointer input so a tap that missed
        # the button can't reach the Setup button underneath, and so tapping
        # the backdrop is not a way to slip past the update.
        return event.type in (
            pygame.MOUSEBUTTONDOWN,
            pygame.MOUSEBUTTONUP,
            pygame.MOUSEMOTION,
            pygame.FINGERDOWN,
            pygame.FINGERUP,
            pygame.FINGERMOTION,
        )
