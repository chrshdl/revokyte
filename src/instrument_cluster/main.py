import os
import signal
import sys

import pygame

from .config import Config, ConfigManager
from .core.plugin_system.plugin_manager import PluginManager
from .core.system.wifi_manager import WifiManager
from .core.vehicle.vehicle_bus import VehicleBus
from .logger import Logger
from .peripherals.display import Display
from .extensions import runtime as extensions
from .signals.signal_pipeline import SignalPipeline
from .states.gate import entry_state
from .states.state_manager import StateManager
from .states.wifi_connecting_state import WifiConnectingState
from .ui.window_layering import WindowManager

logger = Logger("InstrumentClusterOS").get()


def run(conf: Config) -> None:
    # no real audio device on the Pi
    os.environ["SDL_AUDIODRIVER"] = "dummy"

    def handle_exit(sig, frame):
        logger.info("Exit signal received. Closing dashboard ...")
        state_manager.is_running = False

    # register OS signals for systemd compatibility
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    pygame.init()
    pygame.mouse.set_visible(True)

    display = None
    try:
        # Initialize the rendering pipeline. Display resolves which physical
        # panel we're driving and registers it process-wide so input mapping
        # (button.py) can translate physical input into logical 1280x720
        # coordinates. The whole UI is drawn into a fixed logical surface;
        # Display presents it to the panel (rotate and/or scale).
        display = Display(getattr(conf, "display", "auto"))
        main_surface = display.surface

        vehicle_bus = VehicleBus()

        plugin_dir = os.path.join(os.path.dirname(__file__), "plugins")
        plugin_manager = PluginManager(plugin_dir, vehicle_bus)

        signal_pipeline = SignalPipeline()

        state_manager = StateManager(main_surface, vehicle_bus)
        # States reach the plugin manager through the state manager (e.g.
        # a settings change that rebuilds the plugin layout).
        state_manager.plugin_manager = plugin_manager

        # Automotive-style window layering: the state manager is
        # the BASE layer. Overlay windows are composited above
        # it every frame (refer to ui/window_layering.py).
        window_manager = WindowManager(state_manager)

        # Installed extension distributions wire themselves in here; with
        # none installed this is a silent no-op. Wired before load_plugins
        # so an extension can install its feature provider on the plugin
        # manager first (see extensions.py).
        extensions.load(
            vehicle_bus=vehicle_bus,
            state_manager=state_manager,
            window_manager=window_manager,
            plugin_manager=plugin_manager,
        )
        plugin_manager.load_plugins()

        # First-boot Wi-Fi gate: if this device drives Wi-Fi and isn't already
        # associated, show WifiConnectingState which polls for up to 15 s and
        # transitions on success or to WifiSetupState on timeout. On dev
        # machines (no wlan0) this is skipped entirely.
        #
        # After connectivity, entry_state() hands off to the dashboard —
        # nothing else gates the boot.
        wifi = WifiManager()
        if wifi.available and not wifi.is_associated():
            logger.info("Wi-Fi not yet associated; showing connecting screen.")
            state_manager.push_state(
                WifiConnectingState(
                    state_manager,
                    manager=wifi,
                    plugin_manager=plugin_manager,
                    pipeline=signal_pipeline,
                )
            )
        else:
            state_manager.push_state(
                entry_state(state_manager, signal_pipeline, plugin_manager)
            )

        # notify systemd that initialization is complete
        vehicle_bus.health.notify_ready()

        clock = pygame.time.Clock()

        while state_manager.is_running:
            dt = clock.tick(60) / 1000

            vehicle_bus.tick(dt)
            vehicle_bus.merge_signals(extensions.update_signals())
            signal_pipeline.update(vehicle_bus, dt)
            # Plugin reloads may be requested from background threads
            # (extensions do) but execute here — pygame surfaces must be
            # created on the main thread.
            if plugin_manager.consume_reload_request():
                plugin_manager.reload_plugins()
            plugin_manager.update(dt)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    state_manager.is_running = False
                window_manager.handle_event(event)

            window_manager.update(dt)
            display.present(window_manager.draw(main_surface))

    except Exception as e:
        logger.error(f"Critical system error: {e}", exc_info=True)
        # don't sys.exit here — let finally clean up first

    finally:
        logger.info("Cleaning up resources...")
        extensions.stop()
        # Capture any in-memory config changes that were never queued (e.g.
        # quitting while a settings view is still open — shutdown doesn't
        # unwind the state stack, so no exit() runs) and wait for the
        # background writer to drain. Runs after extensions.stop() so
        # extension stop hooks can still mutate config. A no-change persist
        # is skipped by the writer, so this is free in the common case.
        ConfigManager.persist()
        if not ConfigManager.flush(timeout=2.0):
            logger.warning("Config flush timed out; latest changes may not be on disk")
        if display is not None:
            display.close()
        pygame.quit()


def main() -> None:
    try:
        run(ConfigManager.get_config())
    except Exception as e:
        logger.critical(f"Application failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
