from __future__ import annotations

from ..peripherals.backlight import Backlight
from ..config import ConfigManager
from ..logger import Logger
from ..extensions import runtime as extensions
from ..telemetry.mode import TelemetryMode
from ..states.state_manager import StateManager
from ..ui.events import (
    BRIGHTNESS_DOWN_RELEASED,
    BRIGHTNESS_UP_RELEASED,
    BUTTON_BACK_RELEASED,
    DIFF_REFERENCE_MODE_SELECTED,
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

        # load brightness from config, we do not read the hardware here.
        self.initial_brightness = ConfigManager.get_config().brightness
        self.current_brightness = self.initial_brightness

        # Track the values we started with so we only hit the SD card once,
        # on exit, and only if something actually changed — not on every
        # dropdown open/close/reselect.
        self.initial_telemetry_mode = ConfigManager.get_config().telemetry_mode
        self.initial_diff_reference_mode = ConfigManager.get_config().diff_reference_mode
        self.initial_status_lights = ConfigManager.get_config().status_lights

    def background_color(self):
        # return the color defined in the view
        return self.view.background_color

    def draw_static_background(self, bg):
        # delegate drawing to the view
        self.view.draw_static_elements(bg)

    def enter(self, screen):
        super().enter(screen)

        # ensure hardware matches our config (e.g. after a reboot)
        if self._backlight.available:
            self._backlight.set_percent(self.current_brightness)
        # update UI
        self.view.set_brightness_text(self.current_brightness)

    def exit(self):
        # clean up view state
        self.view.close_dropdowns()
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

        # Rows contributed by extensions (none installed = none shown).
        for entry in extensions.setup_entries:
            if event.type == entry.released:
                self.state_manager.change_state(
                    entry.make_state(self.state_manager)
                )
                return True

        if event.type == WIFI_SETUP_RELEASED:
            from .wifi_setup_state import ENTRY_SETTINGS, WifiSetupState

            self.state_manager.push_state(
                WifiSetupState(self.state_manager, entry=ENTRY_SETTINGS)
            )
            return True

        return False

    def on_back_released(self):
        # Only hit the SD card once, and only if something actually changed
        # relative to what we started with — dropdown opens/closes/reselects
        # and brightness nudges all stay in-memory until now.
        cfg = ConfigManager.get_config()
        changed = False

        if self.current_brightness != self.initial_brightness:
            self.logger.info(f"Saving new brightness: {self.current_brightness}%")
            ConfigManager.set_brightness_percent(self.current_brightness, persist=False)
            changed = True

        if cfg.telemetry_mode != self.initial_telemetry_mode:
            changed = True
        if cfg.diff_reference_mode != self.initial_diff_reference_mode:
            changed = True
        if cfg.status_lights != self.initial_status_lights:
            changed = True

        if changed:
            self.logger.info("Persisting setup changes to disk")
            ConfigManager.persist()

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
        # Cclculate new transient value
        new_val = max(10, min(100, self.current_brightness + delta_percent))

        if new_val != self.current_brightness:
            self.current_brightness = new_val

            self._backlight.set_percent(new_val)
            self.view.set_brightness_text(new_val)

            # NOTE: We explicitly DO NOT save to ConfigManager here.
