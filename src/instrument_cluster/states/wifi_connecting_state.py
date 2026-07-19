from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.system.wifi_manager import WifiManager
from ..logger import Logger
from ..states.state import State
from ..ui.views.wifi_setup_view import WifiSetupView

if TYPE_CHECKING:
    from ..core.plugin_system.plugin_manager import PluginManager
    from ..signals.signal_pipeline import SignalPipeline
    from ..states.state_manager import StateManager

_TIMEOUT = 15.0
_POLL_INTERVAL = 0.5
_MIN_DISPLAY = 5.0  # keep screen visible long enough to read


class WifiConnectingState(State):
    """Shown at boot when wpa_supplicant hasn't associated yet.

    Polls is_associated() every 500 ms for up to 15 s. On success the
    dashboard is pushed; on timeout the WiFi setup screen is shown so
    the user can provision credentials.
    """

    def __init__(
        self,
        state_manager: StateManager | None = None,
        manager: WifiManager | None = None,
        plugin_manager: PluginManager | None = None,
        pipeline: SignalPipeline | None = None,
    ):
        super().__init__(state_manager)
        self.logger = Logger(__class__.__name__).get()
        self.manager = manager or WifiManager()
        self.plugin_manager = plugin_manager
        self.pipeline = pipeline

        self.view = WifiSetupView(show_back=False, show_skip=False)
        self.view.show_status(
            "Reconnecting  to  Wi-Fi , please  wait . . .", show_header=True
        )

        self._elapsed: float = 0.0
        self._poll_timer: float = 0.0
        self._associated: bool = False

    # ------------------------------------------------------------------
    # State plumbing
    # ------------------------------------------------------------------
    def background_color(self):
        return self.view.background_color

    def draw_static_background(self, bg):
        pass

    def create_group(self):
        return None

    def full_paint(self, surface):
        self.view.full_paint(surface, self.background)

    def draw(self, surface):
        return self.view.draw(surface, self.background)

    # ------------------------------------------------------------------
    # update
    # ------------------------------------------------------------------
    def update(self, dt):
        super().update(dt)
        self.view.update(dt)

        self._elapsed += dt
        self._poll_timer += dt

        if self._poll_timer >= _POLL_INTERVAL:
            self._poll_timer = 0.0
            if not self._associated and self.manager.is_associated():
                self._associated = True
                self.logger.info("Wi-Fi associated; waiting for minimum display time.")

        if self._associated and self._elapsed >= _MIN_DISPLAY:
            self.logger.info("Proceeding to dashboard.")
            self._enter_dashboard()
            return

        if self._elapsed >= _TIMEOUT:
            self.logger.warning("Wi-Fi association timed out; showing setup.")
            self._enter_wifi_setup()

    # ------------------------------------------------------------------
    # transitions
    # ------------------------------------------------------------------
    def _enter_dashboard(self):
        # Route through the entry gate — always the dashboard.
        from ..states.gate import entry_state

        self.state_manager.change_state(
            entry_state(self.state_manager, self.pipeline, self.plugin_manager)
        )

    def _enter_wifi_setup(self):
        from ..states.wifi_setup_state import ENTRY_BOOT, WifiSetupState

        self.state_manager.change_state(
            WifiSetupState(
                self.state_manager,
                manager=self.manager,
                entry=ENTRY_BOOT,
                plugin_manager=self.plugin_manager,
                pipeline=self.pipeline,
            )
        )
