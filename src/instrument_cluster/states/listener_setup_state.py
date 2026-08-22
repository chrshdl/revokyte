from __future__ import annotations

from typing import TYPE_CHECKING

from ..config import ConfigManager
from ..peripherals.display import is_raspberry_pi
from ..states.agent_setup_state import cluster_lan_ip
from ..states.install_state import InstallState
from ..states.state import State
from ..telemetry.mode import TelemetryMode
from ..ui.events import BUTTON_BACK_RELEASED, LISTENER_CONTINUE_RELEASED
from ..ui.views.listener_setup_view import ListenerSetupView

if TYPE_CHECKING:
    from ..addons.feeds import FeedDescriptor
    from ..states.state_manager import StateManager


class ListenerSetupState(State):
    """Setup screen for a feed that listens rather than connects out.

    Some games (Forza Horizon 6's "Data Out") push telemetry to whatever
    address and port the player configures in-game, rather than exposing
    something this device connects to. There is nothing to type on the
    cluster — the address the player needs is this device's own — so this
    screen shows it instead of running the IP keypad, then proceeds straight
    to the normal signed-tarball install (``InstallState``), passing the
    address only because ``install_from_url`` needs a non-empty value; the
    feed's ``env_builder`` never uses it.

    On desktop, a feed with a ``direct_reader`` skips the install entirely —
    same carve-out ``EnterIPState`` makes — and reads the feed in-process
    instead; ``direct_host`` still gets the cluster's own address, purely to
    satisfy ``SignalPipeline._make_direct_reader``'s non-empty check, since
    the reader itself ignores it.
    """

    def __init__(
        self,
        state_manager: StateManager = None,
        descriptor: "FeedDescriptor" = None,
    ):
        super().__init__(state_manager)
        self.descriptor = descriptor
        self.view = ListenerSetupView(
            feed_label=descriptor.label if descriptor else None
        )
        self._ip = ""

    def background_color(self):
        return self.view.background_color

    def draw_static_background(self, bg):
        self.view.draw_static_elements(bg)

    def create_group(self):
        return None

    def enter(self, screen):
        rects = super().enter(screen)
        self._ip = cluster_lan_ip()
        if not self._ip:
            self.view.set_error("No network connection")
        else:
            self.view.set_address(f"{self._ip}:{self.descriptor.listener_port}")
            self.view.set_status("Enter this address, then press Continue")
        return rects

    def full_paint(self, surface):
        self.view.full_paint(surface, self.background)

    def draw(self, surface):
        return self.view.draw(surface, self.background)

    def update(self, dt):
        super().update(dt)
        self.view.update(dt)

    def handle_event(self, event) -> bool:
        self.view.handle_event(event)

        if event.type == BUTTON_BACK_RELEASED:
            return self.on_back_released()

        if event.type == LISTENER_CONTINUE_RELEASED:
            return self.on_continue_released()

        return False

    def on_back_released(self):
        from .setup_state import SetupState

        self.state_manager.change_state(SetupState(self.state_manager))
        return True

    def on_continue_released(self):
        if not self._ip:
            return True

        if (
            self.descriptor is not None
            and self.descriptor.direct_reader is not None
            and not is_raspberry_pi()
        ):
            ConfigManager.set_telemetry_mode(TelemetryMode.DIRECT, persist=False)
            ConfigManager.set_telemetry_feed(self.descriptor.id, persist=False)
            ConfigManager.set_direct_host(self._ip, persist=False)
            self.state_manager.pop_state()
            return True

        self.state_manager.change_state(
            InstallState(
                self.state_manager, descriptor=self.descriptor, ip=self._ip
            )
        )
        return True
