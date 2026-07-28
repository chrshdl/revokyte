from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from ..addons.installer import (
    FeedRateLimited,
    FeedUnreachable,
    FeedVersionMissing,
    InstallResult,
    install_from_url,
    resolve_pinned_tarball_url,
)
from ..config import ConfigManager
from ..logger import Logger
from ..telemetry.mode import TelemetryMode
from ..states.setup_state import SetupState
from ..states.state import State
from ..ui.events import (
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
    INSTALL_PRESSED,
    INSTALL_RELEASED,
)
from ..ui.views.install_view import InstallView

if TYPE_CHECKING:
    from ..addons.feeds import FeedDescriptor
    from ..states.state_manager import StateManager


# DNS is not ready the instant a DHCP lease arrives — systemd-resolved
# writes the servers a moment later — so the first lookup after joining a
# network fails while the next succeeds. Retry within a window rather than
# for a fixed count: a name that fails to resolve fails in milliseconds and
# gets several attempts, while a network that hangs burns its timeout once
# and gives up instead of making the user wait three times over.
_LOOKUP_RETRY_WINDOW_S = 10.0
_LOOKUP_RETRY_PAUSE_S = 2.0


class _AssetMissing(Exception):
    """The pinned release exists but carries no installable asset."""


def _unreachable_message() -> str:
    """Say what could not be reached, without contradicting ourselves.

    An IP address means the network is up and only the request failed;
    printing "no network connection" next to the device's own address
    sends the reader after the wrong problem. Without an address, name
    networkd's link state instead — a release image has no SSH.
    """
    try:
        from ..core.system.wifi_manager import WifiManager

        manager = WifiManager()
        if not manager.available:
            return "Could not reach GitHub. Try again."
        address = manager.ipv4_address()
        if address:
            return f"Could not reach GitHub. Try again.  ({address})"
        state = manager.link_state()
        if state:
            return f"No network connection.  (no IP, link: {state})"
        return "No network connection."
    except Exception:
        return "Could not reach GitHub. Try again."


def _resolve_pinned_url(descriptor: FeedDescriptor) -> str:
    """Resolve the pinned release's asset, retrying a transient outage.

    Raises the installer's own exceptions; rate limiting and a missing
    version are not retried, because waiting two seconds cannot fix either.
    """
    deadline = time.monotonic() + _LOOKUP_RETRY_WINDOW_S
    while True:
        try:
            url = resolve_pinned_tarball_url(descriptor)
            break
        except FeedRateLimited:
            raise
        except FeedUnreachable:
            if time.monotonic() >= deadline:
                raise
            time.sleep(_LOOKUP_RETRY_PAUSE_S)
    if not url:
        raise _AssetMissing(
            f"The {descriptor.label} {descriptor.version} release has no "
            f"installable asset."
        )
    return url


class InstallState(State):
    """
    Downloads and installs a telemetry feed's self-contained tarball, as
    described by the given FeedDescriptor (game-neutral — see addons/feeds.py).
    """

    def __init__(
        self,
        state_manager: StateManager = None,
        descriptor: "FeedDescriptor" = None,
        ip: str = "",
        auto_start: bool = False,
    ):
        super().__init__(state_manager)
        self.logger = Logger(__class__.__name__).get()

        self.descriptor = descriptor
        self.ip = (ip or "").strip()
        # Set when the decision was already made elsewhere (the stale-feed
        # notice's "Update now"). Asking again would be a second
        # confirmation for one choice, so the screen only reports progress.
        self.auto_start = bool(auto_start)
        self.view = InstallView(
            feed_label=descriptor.label if descriptor else None,
            updating=self.auto_start,
        )

        self._is_installing: bool = False
        self._install_thread: threading.Thread | None = None
        self._install_result: InstallResult | None = None
        self._install_exception: Exception | None = None

    def enter(self, screen):
        rects = super().enter(screen)
        if self.auto_start:
            self._start_install()
        return rects

    def background_color(self):
        return self.view.background_color

    def draw_static_background(self, bg):
        self.view.draw_static_elements(bg)

    def create_group(self):
        return None

    def full_paint(self, surface):
        self.view.full_paint(surface, self.background)

    def draw(self, surface):
        return self.view.draw(surface, self.background)

    def update(self, dt):
        super().update(dt)
        self.view.update(dt)

        if self._install_exception is not None:
            exc = self._install_exception
            self._install_exception = None
            self._install_result = None
            self.view.set_error(self._error_text(exc))

        elif self._install_result is not None:
            res = self._install_result
            self._install_result = None

            if not res.ok:
                self.view.set_error(res.message or "Install failed.")
            else:
                self._finalize_success()

    def handle_event(self, event) -> bool:
        self.view.handle_event(event)

        if event.type in (BUTTON_BACK_PRESSED, INSTALL_PRESSED):
            return True

        if event.type == BUTTON_BACK_RELEASED:
            self.state_manager.change_state(SetupState(self.state_manager))
            return True

        if event.type == INSTALL_RELEASED:
            if not self._is_installing:
                self._start_install()
            return True

        return False

    def _start_install(self):
        """
        Start the installation process in a background thread.
        """

        self.view.set_error("")
        self.view.set_status("")

        if self.descriptor is None:
            self.view.set_error("No telemetry feed selected.")
            return

        if not self.ip:
            self.view.set_error("IP not set. Enter it first.")
            return

        self.view.set_status("Downloading and installing...")
        self._is_installing = True
        self._install_exception = None
        self._install_result = None

        descriptor = self.descriptor
        ip = self.ip

        def worker():
            # The release lookup runs here, not on the main loop: it can
            # block for its full 30 s timeout against a network that hangs
            # rather than refuses, and the service is started with
            # WatchdogSec=30 — a stall there costs the app, not just a
            # frame.
            try:
                url = _resolve_pinned_url(descriptor)
                res: InstallResult = install_from_url(
                    url=url,
                    descriptor=descriptor,
                    ip=ip,
                )
                self._install_result = res
                self._install_exception = None
            except Exception as e:
                self._install_result = None
                self._install_exception = e
            finally:
                self._is_installing = False

        self._install_thread = threading.Thread(target=worker, daemon=True)
        self._install_thread.start()

    def _error_text(self, exc: Exception) -> str:
        """The user-facing sentence for a failed install.

        Each cause needs a different action from the reader, so none of
        them may collapse into a generic failure: a missing pinned version
        is a packaging fault, rate limiting means wait, unreachable means
        check the network.
        """
        if isinstance(exc, FeedVersionMissing):
            self.logger.error(f"Pinned feed release missing: {exc}")
            return (
                f"{self.descriptor.label} {self.descriptor.version} is not "
                f"available. This image needs an update."
            )
        # Checked before FeedUnreachable, its base: the device is online and
        # the fix is to wait, not to touch the network.
        if isinstance(exc, FeedRateLimited):
            self.logger.error(f"Feed release lookup rate-limited: {exc}")
            return "GitHub is rate-limiting this network. Try again in a few minutes."
        if isinstance(exc, FeedUnreachable):
            self.logger.error(f"Feed release lookup failed: {exc}")
            return _unreachable_message()
        if isinstance(exc, _AssetMissing):
            self.logger.error(str(exc))
            return str(exc)
        self.logger.error(f"Install failed: {exc}", exc_info=exc)
        return f"Install failed: {exc}"

    def _finalize_success(self):
        """
        Handle successful install on the main thread.
        The config write is queued here; DashboardState.on_resume() will detect
        the change and switch telemetry mode appropriately.
        """
        # Every feed streams NDJSON to localhost, so the runtime mode is always
        # UDP; telemetry_feed records *which* feed for the settings selection.
        ConfigManager.set_telemetry_mode(TelemetryMode.UDP, persist=False)
        # Record the build, not just which feed: a later image compares it
        # against its own pin to notice a device left on a stale feed.
        ConfigManager.set_telemetry_feed(
            self.descriptor.id, self.descriptor.version
        )

        # Just pop state and return to dashboard
        # DashboardState.on_resume() will call _reconfigure_telemetry_if_needed()
        # which uses switch_mode() to properly reuse cached readers
        self.state_manager.pop_state()
