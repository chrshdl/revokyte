"""Dashboard preview — the per-skin authoring loop.

Renders the standard dashboard with demo telemetry on any display profile:

    python tools/preview_dashboard.py --display waveshare_5

Interactive by default (Q quits). ``--shot PATH`` runs headless on the SDL
dummy driver: the demo session plays for ``--settle`` seconds so the gauges
hold real values, one frame is saved as a PNG, and the process exits — so a
skin edit can be eyeballed (or diffed) without hardware:

    python tools/preview_dashboard.py --display waveshare_5 \
        --shot /tmp/dash_800.png
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _write_config(path: Path, status_lights: bool) -> None:
    path.write_text(
        json.dumps({"telemetry_mode": "demo", "status_lights": status_lights})
    )
    os.environ["IC_CONFIG_PATH"] = str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default="auto", help="display profile")
    parser.add_argument(
        "--shot", default=None, help="save a PNG here and exit (headless)"
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=2.0,
        help="seconds of demo playback before the screenshot",
    )
    parser.add_argument(
        "--status-lights",
        action="store_true",
        help="enable the bezel LED strips",
    )
    parser.add_argument(
        "--quit-after", type=float, default=None, help="exit after N seconds"
    )
    args = parser.parse_args()

    if args.shot:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

    _write_config(Path("/tmp/ic_preview_dashboard.json"), args.status_lights)

    import pygame

    import instrument_cluster
    from instrument_cluster.core.plugin_system.plugin_manager import PluginManager
    from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus
    from instrument_cluster.peripherals.display import Display
    from instrument_cluster.signals.signal_pipeline import SignalPipeline
    from instrument_cluster.states.gate import build_dashboard
    from instrument_cluster.states.state_manager import StateManager
    from instrument_cluster.ui.window_layering import WindowManager

    pygame.init()
    display = Display(args.display)
    surface = display.surface

    bus = VehicleBus()
    state_manager = StateManager(surface, bus)
    plugin_manager = PluginManager(
        os.path.join(os.path.dirname(instrument_cluster.__file__), "plugins"), bus
    )
    plugin_manager.load_plugins()
    state_manager.plugin_manager = plugin_manager

    pipeline = SignalPipeline()
    dashboard = build_dashboard(
        state_manager, pipeline=pipeline, plugin_manager=plugin_manager
    )
    state_manager.push_state(dashboard)
    window_manager = WindowManager(state_manager)

    display.present_full()

    clock = pygame.time.Clock()
    running = True
    elapsed = 0.0

    while running:
        dt = clock.tick(60) / 1000
        elapsed += dt

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key in (
                pygame.K_ESCAPE,
                pygame.K_q,
            ):
                running = False
            window_manager.handle_event(event)

        pipeline.update(bus, dt)
        plugin_manager.update(dt)
        window_manager.update(dt)
        display.present(window_manager.draw(surface))

        if args.shot and elapsed >= args.settle:
            pygame.image.save(surface, args.shot)
            print(f"[preview] saved {args.shot} ({surface.get_size()})")
            running = False
        if args.quit_after is not None and elapsed >= args.quit_after:
            running = False

    dashboard.exit()
    pygame.quit()


if __name__ == "__main__":
    main()
