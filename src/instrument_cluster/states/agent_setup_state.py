from __future__ import annotations

import socket
import threading
from typing import TYPE_CHECKING

from ..addons.agent_server import AgentHandoffServer, AgentUnavailable, prepare_bundle
from ..config import ConfigManager
from ..logger import Logger
from ..states.state import State
from ..telemetry.mode import TelemetryMode
from ..ui.events import AGENT_BASIC_RELEASED, BUTTON_BACK_RELEASED
from ..ui.views.agent_setup_view import AgentSetupContext, AgentSetupView

if TYPE_CHECKING:
    from ..addons.feeds import FeedDescriptor
    from ..states.state_manager import StateManager


def cluster_lan_ip() -> str:
    """This device's address on the LAN, as the game PC would reach it.

    Opening a UDP socket toward an off-link address makes the routing table
    pick the interface that actually carries LAN traffic, which is more
    reliable than resolving the hostname — that answers 127.0.1.1 on a stock
    Debian image, which is exactly the wrong address to print on this screen.
    No packet is sent.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1, guaranteed unrouted
        return probe.getsockname()[0]
    except OSError:
        return ""
    finally:
        probe.close()


class AgentSetupState(State):
    view_class = AgentSetupView

    """Pairing screen for a feed whose PC agent unlocks the rest of its data.

    Preparing the bundle means a download and a signature check, so it happens
    on a worker thread and the view reports progress; the screen is usable (and
    cancellable) throughout. The little web server lives exactly as long as this
    state does — see :meth:`exit`.
    """

    def __init__(
        self,
        state_manager: StateManager = None,
        descriptor: "FeedDescriptor" = None,
    ):
        super().__init__(state_manager)
        self.logger = Logger(__class__.__name__).get()

        self.descriptor = descriptor
        self._server: AgentHandoffServer | None = None
        self._worker: threading.Thread | None = None
        self._cancelled = threading.Event()
        self._ip = ""
        # Bumped on every entry; a worker captures it and only writes to the
        # view while it still matches. _live_epoch is None while off screen.
        self._epoch = 0
        self._live_epoch: int | None = None

    def view_context(self):
        agent = self.descriptor.agent if self.descriptor else None
        return AgentSetupContext(
            feed_label=self.descriptor.label if self.descriptor else None,
            unlocks=agent.unlocks if agent else None,
        )

    def enter(self, screen):
        rects = super().enter(screen)
        self._cancelled.clear()
        self._epoch += 1
        self._live_epoch = self._epoch
        self._ip = cluster_lan_ip()
        if not self._ip:
            self.view.set_error("No network connection")
            return rects
        port = self.descriptor.agent.port
        self.view.set_url(f"http://{self._ip}:{port}")
        self.view.set_status("Preparing download...")

        self._worker = threading.Thread(
            target=self._prepare, name="agent-prepare", daemon=True
        )
        self._worker.start()
        return rects

    def _publish(self, setter: str, text: str) -> None:
        """Write to the view from the worker thread, if it is still ours.

        The view outlives this state, so a worker that finishes after the user
        has left would otherwise paint a stale error onto whatever screen is
        showing now — or onto this screen's *next* visit, after reset() had
        cleared it. The epoch is taken in enter() and dropped in exit(), the
        same generation guard WifiSetupState uses for its connect worker.
        """
        if self._cancelled.is_set() or self._epoch != self._live_epoch:
            self.logger.info("Abandoned agent worker wanted to say: %s", text)
            return
        view = self.view
        if view is not None:
            getattr(view, setter)(text)

    def _prepare(self):
        """Fetch, verify and serve the bundle. Runs off the UI thread."""
        try:
            bundle = prepare_bundle(self.descriptor, self._ip)
        except AgentUnavailable as e:
            self.logger.error("agent bundle unavailable: %s", e)
            self._publish("set_error", str(e))
            return
        except Exception as e:  # noqa: BLE001 - never take the UI down with us
            self.logger.exception("agent bundle failed")
            self._publish("set_error", f"Download failed: {e}")
            return

        if self._cancelled.is_set():
            return

        server = AgentHandoffServer(bundle, self.descriptor, self.descriptor.agent.port)
        try:
            server.start()
        except OSError as e:
            self._publish("set_error", f"Could not open port: {e}")
            return
        self._server = server
        # Apply the config now, while the user is still at their PC. The
        # reader itself rebinds when the dashboard resumes and
        # SignalPipeline.sync_mode() picks up the changed udp_host —
        # frames the agent sends before then are dropped harmlessly (the
        # protocol is stateless; the next frame supersedes everything).
        self.apply_full_mode()
        if bundle.verified:
            self._publish("set_status", "Ready - open the address above on your PC")
        else:
            # Says it here as well as on the download page: whoever is standing
            # at the cluster should not have to visit the page to find out it
            # is serving something unsigned.
            self._publish(
                "set_error", "UNVERIFIED build - open the address to read why"
            )

    def exit(self):
        # The pairing window closes with the screen: nothing keeps listening
        # once the user walks away from it.
        self._cancelled.set()
        self._live_epoch = None
        if self._server is not None:
            self._server.stop()
            self._server = None
        super().exit()

    def update(self, dt):
        super().update(dt)
        self.view.update(dt)

    def handle_event(self, event):
        self.view.handle_event(event)

        if event.type == BUTTON_BACK_RELEASED:
            return self.on_back_released()

        if event.type == AGENT_BASIC_RELEASED:
            return self.on_basic_released()

        return False

    def on_back_released(self):
        from .setup_state import SetupState

        self.state_manager.change_state(SetupState(self.state_manager))
        return True

    def on_basic_released(self):
        """Fall back to the network-only feed: the normal IP-entry install."""
        from .enter_ip_state import EnterIPState

        self.state_manager.change_state(
            EnterIPState(
                state_manager=self.state_manager,
                descriptor=self.descriptor,
                recent_connected=ConfigManager.get_config().recent_connected or [],
            )
        )
        return True

    def apply_full_mode(self):
        """Config for a PC agent feeding this device directly.

        No proxy is installed: the agent produces whole frames itself, so the
        cluster is simply a UDP NDJSON listener — but on the LAN interface,
        because the sender is another machine. The wildcard bind takes
        effect on the next dashboard resume via SignalPipeline.sync_mode()
        (which rebinds the reader when udp_host changed), not at some
        future reboot.
        """
        ConfigManager.set_telemetry_mode(TelemetryMode.UDP, persist=False)
        ConfigManager.set_telemetry_feed(
            self.descriptor.id, self.descriptor.version, persist=False
        )
        ConfigManager.set_udp_host("0.0.0.0", persist=True)
