from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from ..addons.installer import (
    FeedUnreachable,
    InstallResult,
    install_from_url,
    resolve_latest_tarball_url,
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


def _network_detail() -> str:
    """The device's IP, or networkd's link state when it has none.

    Best-effort and never fatal: this only decorates an error message.
    """
    try:
        from ..core.system.wifi_manager import WifiManager

        manager = WifiManager()
        if not manager.available:
            return ""
        address = manager.ipv4_address()
        if address:
            return f"({address})"
        state = manager.link_state()
        return f"(no IP, link: {state})" if state else "(no IP address)"
    except Exception:
        return ""


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
    ):
        super().__init__(state_manager)
        self.logger = Logger(__class__.__name__).get()

        self.descriptor = descriptor
        self.ip = (ip or "").strip()
        self.view = InstallView(
            feed_label=descriptor.label if descriptor else None,
        )

        self._is_installing: bool = False
        self._install_thread: threading.Thread | None = None
        self._install_result: InstallResult | None = None
        self._install_exception: Exception | None = None

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
            self.view.set_error(f"Install failed: {self._install_exception}")
            self._install_exception = None
            self._install_result = None

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

        try:
            url = resolve_latest_tarball_url(self.descriptor)
        except FeedUnreachable as e:
            # Being offline is by far the likeliest cause and needs a
            # completely different fix than a missing release, so say so —
            # and name the link state, since a release image has no SSH.
            self.logger.error(f"Feed release lookup failed: {e}")
            self.view.set_error(f"No network connection. {_network_detail()}".strip())
            return
        if not url:
            self.view.set_error(
                f"Could not find the latest {self.descriptor.label} release."
            )
            return

        self.view.set_status("Downloading and installing...")
        self._is_installing = True
        self._install_exception = None
        self._install_result = None

        descriptor = self.descriptor
        ip = self.ip

        def worker():
            try:
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

    def _finalize_success(self):
        """
        Handle successful install on the main thread.
        The config write is queued here; DashboardState.on_resume() will detect
        the change and switch telemetry mode appropriately.
        """
        # Every feed streams NDJSON to localhost, so the runtime mode is always
        # UDP; telemetry_feed records *which* feed for the settings selection.
        ConfigManager.set_telemetry_mode(TelemetryMode.UDP, persist=False)
        ConfigManager.set_telemetry_feed(self.descriptor.id)

        # Just pop state and return to dashboard
        # DashboardState.on_resume() will call _reconfigure_telemetry_if_needed()
        # which uses switch_mode() to properly reuse cached readers
        self.state_manager.pop_state()
