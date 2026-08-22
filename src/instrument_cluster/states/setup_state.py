from __future__ import annotations

from ..config import ConfigManager
from ..extensions import runtime as extensions
from ..logger import Logger
from ..peripherals.backlight import Backlight
from ..states.state_manager import StateManager
from ..telemetry.mode import TelemetryMode
from ..ui.events import (
    BRIGHTNESS_DOWN_RELEASED,
    BRIGHTNESS_UP_RELEASED,
    BUTTON_BACK_RELEASED,
    DIFF_REFERENCE_MODE_SELECTED,
    SOFTWARE_RELEASED,
    SHIFT_LIGHTS_TOGGLED,
    STATUS_LIGHTS_TOGGLED,
    TELEMETRY_MODE_SELECTED,
    WIFI_SETUP_RELEASED,
)
from ..ui.views.setup_view import SetupView
from .state import State


class SetupState(State):
    def __init__(self, state_manager: StateManager | None = None):
        super().__init__(state_manager)
        self.logger = Logger(__class__.__name__).get()

        self.view = SetupView()
        self._backlight = Backlight()

    def background_color(self):
        # return the color defined in the view
        return self.view.background_color

    def draw_static_background(self, bg):
        # delegate drawing to the view
        self.view.draw_static_elements(bg)

    def enter(self, screen):
        super().enter(screen)

        # load brightness from config, we do not read the hardware here.
        brightness = ConfigManager.get_config().brightness
        # ensure hardware matches our config (e.g. after a reboot)
        if self._backlight.available:
            self._backlight.set_percent(brightness)
        # update UI
        self.view.set_brightness_text(brightness)

    def exit(self):
        # clean up view state
        self.view.close_dropdowns()
        # All settings changes were applied in-memory (persist=False) as they
        # happened; queue the single disk write here so every way of leaving
        # the view — back button, change_state to another settings screen —
        # flushes them. A no-change visit costs nothing: the writer skips
        # snapshots identical to what's already on disk.
        ConfigManager.persist()
        super().exit()

    def create_group(self):
        # override to prevent State from creating a default group
        return None

    def full_paint(self, surface):
        self.view.full_paint(surface, self.background)

    def draw(self, surface):
        # Delegate to view
        return self.view.draw(surface, self.background)

    def update(self, dt):
        super().update(dt)
        self.view.update(dt)

    def handle_event(self, event):
        # view handles interactions
        if self.view.handle_event(event):
            return True

        if event.type == BUTTON_BACK_RELEASED:
            return self.on_back_released()

        if event.type == BRIGHTNESS_DOWN_RELEASED:
            self.adjust_brightness(-SetupView.STEP_PERCENT)
            return True

        if event.type == BRIGHTNESS_UP_RELEASED:
            self.adjust_brightness(+SetupView.STEP_PERCENT)
            return True

        if event.type == TELEMETRY_MODE_SELECTED:
            return self.on_telemetry_selected(event.mode)

        if event.type == DIFF_REFERENCE_MODE_SELECTED:
            # Apply immediately in-memory — DeltaSignal reacts live (e.g. a
            # mid-lap reference switch) — but defer the disk write until
            # the user leaves the view (see on_back_released).
            ConfigManager.set_diff_reference_mode(event.mode, persist=False)
            return True

        if event.type == STATUS_LIGHTS_TOGGLED:
            # Applied in-memory now — DashboardState rebuilds its layout on
            # resume — with the disk write deferred to on_back_released.
            ConfigManager.set_status_lights(event.checked, persist=False)
            return True

        if event.type == SHIFT_LIGHTS_TOGGLED:
            # The LED-bar peripheral reads the flag every update, so the
            # bar reacts on the next dashboard frame; disk write deferred.
            ConfigManager.set_shift_lights(event.checked, persist=False)
            return True

        # Rows contributed by extensions (none installed = none shown).
        for entry in extensions.setup_entries:
            if event.type == entry.released:
                self.state_manager.change_state(entry.make_state(self.state_manager))
                return True

        if event.type == WIFI_SETUP_RELEASED:
            from .wifi_setup_state import ENTRY_SETTINGS, WifiSetupState

            self.state_manager.push_state(
                WifiSetupState(self.state_manager, entry=ENTRY_SETTINGS)
            )
            return True

        if event.type == SOFTWARE_RELEASED:
            from .software_state import SoftwareState

            self.state_manager.push_state(SoftwareState(self.state_manager))
            return True

        return False

    def on_back_released(self):
        # Any pending settings changes are flushed by exit(), which
        # pop_state() invokes on us.
        self.state_manager.pop_state()
        return True

    def on_telemetry_selected(self, choice):
        if choice.demo:
            # Deferred to on_back_released; see DIFF_REFERENCE_MODE_SELECTED.
            ConfigManager.set_telemetry_mode(TelemetryMode.DEMO, persist=False)
        else:
            from ..addons.feeds import feed_by_id
            from .enter_ip_state import EnterIPState

            descriptor = feed_by_id(choice.feed_id)
            # A feed whose richest channels only exist on the game PC leads
            # with the pairing screen: it is the option that gives the driver
            # every gauge, and it needs no IP typed here at all. That screen
            # offers the network-only path as its fallback.
            #
            # Not gated on the appliance. Pairing needs nothing a Pi has and a
            # desktop lacks — serve a file on the LAN, listen on UDP — and a
            # laptop cluster beside a Windows gaming PC is as ordinary a setup
            # as the appliance is. The in-process reader stays reachable via
            # this screen's Basic setup button.
            if descriptor is not None and descriptor.agent is not None:
                from .agent_setup_state import AgentSetupState

                self.state_manager.change_state(
                    AgentSetupState(
                        state_manager=self.state_manager, descriptor=descriptor
                    )
                )
                return True

            # A feed that pushes telemetry to an address we choose, rather
            # than one this device connects out to, needs no IP typed here
            # at all — show it the address instead (see ListenerSetupState).
            if descriptor is not None and descriptor.listener_port is not None:
                from .listener_setup_state import ListenerSetupState

                self.state_manager.change_state(
                    ListenerSetupState(
                        state_manager=self.state_manager, descriptor=descriptor
                    )
                )
                return True

            self.state_manager.change_state(
                EnterIPState(
                    state_manager=self.state_manager,
                    descriptor=descriptor,
                    recent_connected=(
                        ConfigManager.get_config().recent_connected or []
                    ),
                )
            )
        return True


    def adjust_brightness(self, delta_percent: int):
        # UI floor is 10 (never let the user black out the panel), even
        # though the config itself allows 0.
        current = ConfigManager.get_config().brightness
        new_val = max(10, min(100, current + delta_percent))

        if new_val != current:
            # Applied in-memory now, like the dropdowns/toggle above; the
            # disk write is deferred to exit().
            ConfigManager.set_brightness_percent(new_val, persist=False)
            self._backlight.set_percent(new_val)
            self.view.set_brightness_text(new_val)
