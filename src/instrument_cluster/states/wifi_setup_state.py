from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from ..core.system.wifi_manager import Network, WifiManager
from ..logger import Logger
from ..states.state import State
from ..ui.events import (
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
    WIFI_BACKSPACE_RELEASED,
    WIFI_CONNECT_RELEASED,
    WIFI_KEY_RELEASED,
    WIFI_MODE_RELEASED,
    WIFI_NETWORK_SELECTED,
    WIFI_OTHER_SELECTED,
    WIFI_RESCAN_RELEASED,
    WIFI_REVEAL_RELEASED,
    WIFI_SHIFT_RELEASED,
    WIFI_SKIP_RELEASED,
)
from ..ui.views.wifi_setup_view import WifiSetupView

if TYPE_CHECKING:
    from ..core.plugin_system.plugin_manager import PluginManager
    from ..signals.signal_pipeline import SignalPipeline
    from ..states.state_manager import StateManager

ENTRY_BOOT = "boot"  # first-boot gate: proceed to the dashboard on success
ENTRY_SETTINGS = "settings"  # opened from Setup: pop back to the dashboard

# WPA passphrases are 8..63 chars; reject early so we don't bounce the radio.
_MIN_PSK_LEN = 8

# Connect-worker outcomes and the hint each one shows. Only auth failure
# blames the password; setup and DHCP failures name their own layer.
_CONNECT_OK = "ok"
_CONNECT_SETUP_FAILED = "setup-failed"  # config write / service restart raised
_CONNECT_AUTH_FAILED = "auth-failed"  # never associated within the window
_CONNECT_NO_DHCP = "no-dhcp"  # associated but no IP lease
_CONNECT_HINTS = {
    _CONNECT_SETUP_FAILED: "Could  not  save  Wi-Fi  settings.",
    _CONNECT_AUTH_FAILED: "Could  not  connect.  Check  password.",
    _CONNECT_NO_DHCP: "Joined,  but  got  no  IP  address.",
}


class WifiSetupState(State):
    """Let the user join a Wi-Fi network from the display.

    Used both as a first-boot gate (``ENTRY_BOOT`` — replaces itself with the
    dashboard once connected) and from the Setup screen (``ENTRY_SETTINGS`` —
    pops back). Scanning and connecting run on worker threads; ``update()``
    polls their results and drives the view through its scan/password/status
    phases.
    """

    def __init__(
        self,
        state_manager: StateManager | None = None,
        manager: WifiManager | None = None,
        entry: str = ENTRY_BOOT,
        plugin_manager: PluginManager | None = None,
        pipeline: SignalPipeline | None = None,
    ):
        super().__init__(state_manager)
        self.logger = Logger(__class__.__name__).get()

        self.manager = manager or WifiManager()
        self.entry = entry
        self.plugin_manager = plugin_manager
        self.pipeline = pipeline

        # Back is only meaningful when there's something to go back to
        # (settings). On the first-boot gate we instead offer a "Use demo"
        # skip so the device stays usable when no network is available.
        self.view = WifiSetupView(
            show_back=(entry == ENTRY_SETTINGS),
            show_skip=(entry == ENTRY_BOOT),
        )

        self._networks: list[Network] = []
        self._selected_ssid: str | None = None
        self._selected_secured: bool = False
        self._manual: bool = False

        self._scan_thread: threading.Thread | None = None
        self._scan_result: list[Network] | None = None
        self._scan_ssid: str = ""
        self._scanning = False

        self._connect_thread: threading.Thread | None = None
        self._connect_result: bool | None = None
        self._connecting = False

        self._connected_timer: float = 0.0

        if not self.manager.available:
            self.view.show_status("Wi-Fi  not  available", error=True)
        else:
            self._start_scan()

    # ------------------------------------------------------------------
    # State plumbing
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # async work
    # ------------------------------------------------------------------
    def _start_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self._scan_result = None
        self.view.show_scanning()

        # Snapshot the current SSID *before* the scan starts. wpa_cli scan
        # forces an off-channel scan that briefly drops the association, so
        # querying current_ssid() after the scan often returns None.
        ssid_before_scan = self.manager.current_ssid() or ""

        def worker():
            try:
                self._scan_result = self.manager.scan()
            except Exception as e:
                self.logger.error(f"Scan worker failed: {e}")
                self._scan_result = []
            finally:
                self._scan_ssid = ssid_before_scan
                self._scanning = False

        self._scan_thread = threading.Thread(target=worker, daemon=True)
        self._scan_thread.start()

    def _start_connect(self, ssid: str, psk: str | None):
        if self._connecting:
            return
        self._connecting = True
        self._connect_result = None
        self.view.show_status(f"Connecting  to  {ssid} ...")

        def worker():
            # Three distinct failure modes so the hint can say what actually
            # went wrong — release images have no SSH, so the screen is the
            # only diagnostic port and "check password" must not be a
            # catch-all for infrastructure failures.
            try:
                self.manager.connect(ssid, psk)
            except Exception as e:
                self.logger.error(f"Connect worker failed: {e}")
                self._connect_result = _CONNECT_SETUP_FAILED
                self._connecting = False
                return
            try:
                if not self.manager.wait_for_association(timeout=30.0):
                    self._connect_result = _CONNECT_AUTH_FAILED
                elif self.manager.wait_for_connection(timeout=30.0):
                    self._connect_result = _CONNECT_OK
                else:
                    self._connect_result = _CONNECT_NO_DHCP
            finally:
                self._connecting = False

        self._connect_thread = threading.Thread(target=worker, daemon=True)
        self._connect_thread.start()

    def update(self, dt):
        super().update(dt)
        self.view.update(dt)

        if self._connected_timer > 0:
            self._connected_timer -= dt
            if self._connected_timer <= 0:
                self._connected_timer = 0.0
                if self.entry == ENTRY_SETTINGS:
                    self.state_manager.pop_state()
                else:
                    self._enter_dashboard()
            return

        if self._scan_result is not None and not self._scanning:
            self._networks = self._scan_result
            self._scan_result = None
            self.view.show_networks(self._networks, self._scan_ssid)

        if self._connect_result is not None and not self._connecting:
            result = self._connect_result
            self._connect_result = None
            if result == _CONNECT_OK:
                self._on_connected()
            else:
                self.logger.warning(f"Wi-Fi connection failed: {result}")
                self.view.show_password(
                    self._selected_ssid, self._selected_secured, self._manual
                )
                self.view.set_hint(_CONNECT_HINTS[result])

    # ------------------------------------------------------------------
    # success
    # ------------------------------------------------------------------
    def _on_connected(self):
        ssid = self.manager.current_ssid() or self._selected_ssid or ""
        self.logger.info(f"Wi-Fi connected to {ssid}")
        self.view.show_connected(ssid)
        self._connected_timer = 2.0

    def _on_skip(self) -> bool:
        """First-boot 'Use demo' escape hatch: run offline in demo mode."""
        from ..config import ConfigManager
        from ..telemetry.mode import TelemetryMode

        self.logger.info("Wi-Fi setup skipped; starting in offline/demo mode.")
        ConfigManager.set_telemetry_mode(TelemetryMode.DEMO)
        self._enter_dashboard()
        return True

    def _enter_dashboard(self):
        # Route through the entry gate — always the dashboard. The gate
        # links UI plugins exactly as main.run() does.
        from ..states.gate import entry_state

        self.state_manager.change_state(
            entry_state(self.state_manager, self.pipeline, self.plugin_manager)
        )

    # ------------------------------------------------------------------
    # input
    # ------------------------------------------------------------------
    def handle_event(self, event):
        self.view.handle_event(event)

        # swallow press feedback so nothing underneath reacts
        if event.type == BUTTON_BACK_PRESSED:
            return True

        if event.type == BUTTON_BACK_RELEASED:
            return self._on_back()

        if event.type == WIFI_RESCAN_RELEASED:
            self._start_scan()
            return True

        if event.type == WIFI_SKIP_RELEASED:
            return self._on_skip()

        if event.type == WIFI_NETWORK_SELECTED:
            return self._on_network_selected(event)

        if event.type == WIFI_OTHER_SELECTED:
            if self.view.phase != self.view.PHASE_SCAN:
                return True
            self._selected_ssid = None
            self._selected_secured = True
            self._manual = True
            self.view.show_password(None, secured=True, manual=True)
            return True

        if event.type == WIFI_KEY_RELEASED:
            self._insert(getattr(event, "label", ""))
            return True

        if event.type == WIFI_BACKSPACE_RELEASED:
            self._backspace()
            return True

        if event.type == WIFI_SHIFT_RELEASED:
            self.view.toggle_shift()
            return True

        if event.type == WIFI_MODE_RELEASED:
            self.view.toggle_mode()
            return True

        if event.type == WIFI_REVEAL_RELEASED:
            self.view.toggle_reveal()
            return True

        if event.type == WIFI_CONNECT_RELEASED:
            return self._on_connect_pressed()

        return False

    def _on_network_selected(self, event) -> bool:
        # Rows reuse one event for press+release; ignore once we've moved on.
        if self.view.phase != self.view.PHASE_SCAN:
            return True
        ssid = getattr(event, "ssid", "")
        secured = bool(getattr(event, "secured", True))
        if not ssid:
            return True
        self._selected_ssid = ssid
        self._selected_secured = secured
        self._manual = False

        if secured:
            self.view.show_password(ssid, secured=True, manual=False)
        else:
            self._start_connect(ssid, None)
        return True

    def _on_connect_pressed(self) -> bool:
        ssid = self.view.ssid_text() if self._manual else (self._selected_ssid or "")
        psk = self.view.password_text()

        if self._manual and not ssid:
            self.view.set_hint("Enter  a  network  name.")
            return True
        if psk and len(psk) < _MIN_PSK_LEN:
            self.view.set_hint("Password  must  be  8+  characters.")
            return True

        self.view.set_hint("")
        self._selected_ssid = ssid
        self._start_connect(ssid, psk or None)
        return True

    def _on_back(self) -> bool:
        phase = self.view.phase
        if phase == self.view.PHASE_PASSWORD or (
            phase == self.view.PHASE_STATUS and self.view.status_is_error
        ):
            self.view.show_networks(self._networks)
            return True

        # scan phase
        if self.entry == ENTRY_SETTINGS:
            self.state_manager.pop_state()
        return True

    # ------------------------------------------------------------------
    # text field editing (driven by the on-screen keyboard)
    # ------------------------------------------------------------------
    def _insert(self, label: str):
        field = self.view.active_field()
        if field is not None and label:
            field.set_text(field.text + label)

    def _backspace(self):
        field = self.view.active_field()
        if field is not None and field.text:
            field.set_text(field.text[:-1])
