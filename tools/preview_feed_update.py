"""Preview the "telemetry feed out of date" modal over a live dashboard.

The notice only appears when the feed build recorded in config differs from
the version this image pins — a state that is awkward to reach on purpose,
since it needs a device that was set up under an older image. This forges
that config so the card can be judged on demand: its wording, how far the
dashboard is knocked back behind it, and that dismissing it puts the panel
back exactly as it was.

Runs on a desktop window and, unchanged, on the device's own panel. The
dashboard underneath is live demo telemetry, so the dimming is judged
against moving gauges rather than a still.

Controls:

    SPACE    dismiss / bring it back
    + / -    dim strength, 5% at a time (to trial a value on-panel)
    U        toggle "version vX" vs "an unknown build" wording
    Esc / Q  quit

``--cycle`` needs no keyboard, which is what you want on the device: it
shows and dismisses on a timer so the panel walks modal -> live -> modal on
its own.

Usage (from the repo root, venv active):

    python tools/preview_feed_update.py
    python tools/preview_feed_update.py --cycle          # unattended
    python tools/preview_feed_update.py --dim 50
    python tools/preview_feed_update.py --installed-version ""
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pygame  # noqa: E402


def _write_config(path: Path, installed_version: str) -> None:
    """Forge a device that was set up under an older image."""
    path.write_text(
        json.dumps(
            {
                "telemetry_mode": "udp",
                "telemetry_feed": "granturismo",
                "telemetry_feed_version": installed_version,
                "status_lights": False,
            }
        )
    )
    os.environ["IC_CONFIG_PATH"] = str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default="auto", help="display profile")
    parser.add_argument(
        "--installed-version",
        default="v0.3.10",
        help='feed build to claim is installed ("" = unknown build wording)',
    )
    parser.add_argument(
        "--dim",
        type=float,
        default=None,
        help="dim percentage behind the card (default: the app's own)",
    )
    parser.add_argument(
        "--cycle",
        type=float,
        nargs="?",
        const=4.0,
        default=None,
        metavar="SECONDS",
        help="unattended: show and dismiss every SECONDS (default 4)",
    )
    parser.add_argument(
        "--quit-after",
        type=float,
        default=None,
        help="exit after this many seconds (for scripted runs)",
    )
    args = parser.parse_args()

    _write_config(Path("/tmp/ic_preview_feed_update.json"), args.installed_version)

    import instrument_cluster
    from instrument_cluster.addons.feeds import feed_by_id
    from instrument_cluster.config import ConfigManager
    from instrument_cluster.core.plugin_system.plugin_manager import PluginManager
    from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus
    from instrument_cluster.peripherals.display import Display
    from instrument_cluster.signals.signal_keys import SignalKey
    from instrument_cluster.states.gate import build_dashboard
    from instrument_cluster.states.state_manager import StateManager
    from instrument_cluster.telemetry.demo import DemoReader
    from instrument_cluster.ui.feed_update_window import (
        DIM_PERCENT,
        FeedUpdateWindow,
        build_card,
    )
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

    dashboard = build_dashboard(state_manager, plugin_manager=plugin_manager)
    state_manager.push_state(dashboard)

    window_manager = WindowManager(state_manager)
    popup = FeedUpdateWindow(
        ConfigManager.get_config(), state_manager, surface.get_size()
    )
    window_manager.add_window(popup)

    if not popup.sprites:
        print(
            "[preview] nothing to show — the forged config is not stale. "
            "Pass --installed-version with a build the descriptor does not pin."
        )
        return

    dimming, card = popup.sprites[0], popup.sprites[1]
    dim = args.dim if args.dim is not None else DIM_PERCENT
    dimming.set_percent(dim)
    descriptor = feed_by_id("granturismo")
    installed = args.installed_version

    def rearm() -> None:
        """Bring the notice back.

        Reaches past `dismiss()` on purpose: the window is deliberately
        once-per-boot, so re-showing it is not something the product offers
        — and re-checking the card without restarting is the whole point of
        a preview.
        """
        popup._dismissed = False

    def repaint_card() -> None:
        card.image = build_card(descriptor, installed)
        card.dirty = 1

    reader = DemoReader()
    if args.cycle:
        print(f"[preview] cycling every {args.cycle:g}s — no keyboard needed")
    else:
        print("[preview] SPACE dismiss/restore, +/- dim, U wording, Q quit")
    print(f"[preview] dim {dim:g}%, installed {installed or '(unknown)'!r}")

    display.present_full()

    clock = pygame.time.Clock()
    running = True
    elapsed = 0.0
    next_cycle = args.cycle or 0.0

    while running:
        dt = clock.tick(60) / 1000
        elapsed += dt

        if args.cycle and elapsed >= next_cycle:
            next_cycle += args.cycle
            if popup.visible:
                popup.dismiss()
                print("[preview] dismissed (auto)")
            else:
                rearm()
                print("[preview] shown (auto)")

        if args.quit_after is not None and elapsed >= args.quit_after:
            running = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key == pygame.K_SPACE:
                    if popup.visible:
                        popup.dismiss()
                        print("[preview] dismissed")
                    else:
                        rearm()
                        print("[preview] shown")
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS):
                    dim = min(100.0, dim + 5)
                    dimming.set_percent(dim)
                    print(f"[preview] dim {dim:g}%")
                elif event.key == pygame.K_MINUS:
                    dim = max(0.0, dim - 5)
                    dimming.set_percent(dim)
                    print(f"[preview] dim {dim:g}%")
                elif event.key == pygame.K_u:
                    installed = "" if installed else args.installed_version or "v0.3.10"
                    repaint_card()
                    print(f"[preview] installed {installed or '(unknown)'!r}")
            else:
                # Pointer events go through the compositor so the modal's own
                # swallow-and-dismiss behaviour is what gets exercised.
                window_manager.handle_event(event)

        bus.update_frame(reader.latest())
        bus.merge_signals(
            {
                SignalKey.DELTA_DIFF_STABLE: -0.42,
                SignalKey.DELTA_STATE: None,
                SignalKey.DELTA_REFERENCE_MODE: "fastest",
                SignalKey.TRACK_NAME: "Spa-Francorchamps",
                SignalKey.FUEL_LAPS_REMAINING: 12.4,
                SignalKey.FUEL_USED_CURRENT_LAP: 1.2,
            }
        )

        plugin_manager.update(dt)
        window_manager.update(dt)
        display.present(window_manager.draw(surface))

    dashboard.exit()
    pygame.quit()


if __name__ == "__main__":
    main()
