"""Preview what happens when a NOTIFICATION and a SYSTEM_ALERT both want the
screen — and what arbitration does about it.

The two windows the base build registers can collide: a device whose feed
predates the image raises the stale-feed card (NOTIFICATION), and a feed that
old is also a plausible reason for the link to go dead (NO SIGNAL,
SYSTEM_ALERT). Layers only ever settled *pixels*, so both used to draw: the
full-width band cut across the card's lower edge, and the card's 35% dimming
knocked back the very gauges the band marks as stale.

The WindowManager now arbitrates presence as well (see
``ui/window_layering.py``): the topmost visible window owns the policy, and
the alert declares ``occludes_below``, so the card is *withdrawn* — not drawn,
no events — and returns by itself on recovery. This preview is here because
that is a judgement about what a driver sees, and the only way to judge it is
to watch both transitions on the panel.

**A toggles arbitration off**, which is the whole point of the script: it puts
the old overlapping composite back, side by side with the new behaviour, on
the same frame budget and the same live gauges.

Controls:

    SPACE    dead link on / off   (the alert, and so the withdrawal)
    A        arbitration on / off (off = the collision it fixes)
    N        bring the stale-feed card back after it was acted on
    Esc / Q  quit

``--cycle`` needs no keyboard, which is what you want on the device: it walks
card -> card+alert -> recovery on a timer, so both transitions repeat on their
own while you watch the seam.

Usage (from the repo root, venv active):

    python tools/preview_window_arbitration.py
    python tools/preview_window_arbitration.py --cycle          # unattended
    python tools/preview_window_arbitration.py --no-arbitration # start "before"
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pygame  # noqa: E402


def _write_config(path: Path, installed_version: str) -> None:
    """Forge a device set up under an older image, so the card has something
    to say. UDP mode, because demo mode runs no installed feed and the card
    would correctly stay silent."""
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
        help="feed build to claim is installed (must differ from the pin)",
    )
    parser.add_argument(
        "--no-arbitration",
        action="store_true",
        help="start with arbitration off, i.e. the overlapping composite",
    )
    parser.add_argument(
        "--cycle",
        type=float,
        nargs="?",
        const=4.0,
        default=None,
        metavar="SECONDS",
        help="unattended: advance the walk every SECONDS (default 4)",
    )
    parser.add_argument(
        "--quit-after",
        type=float,
        default=None,
        help="exit after this many seconds (for scripted runs)",
    )
    args = parser.parse_args()

    _write_config(Path("/tmp/ic_preview_arbitration.json"), args.installed_version)

    import instrument_cluster
    from instrument_cluster.config import ConfigManager
    from instrument_cluster.core.plugin_system.plugin_manager import PluginManager
    from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus
    from instrument_cluster.peripherals.display import Display
    from instrument_cluster.signals.signal_keys import SignalKey
    from instrument_cluster.states.gate import build_dashboard
    from instrument_cluster.states.state_manager import StateManager
    from instrument_cluster.telemetry.demo import DemoReader
    from instrument_cluster.ui.feed_update_window import FeedUpdateWindow
    from instrument_cluster.ui.no_signal_window import NoSignalWindow
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

    # Registered exactly as main.py does, alert first. No SignalPipeline here:
    # telemetry_stale is driven by hand below, and a running LinkSignal would
    # overwrite it every frame.
    window_manager = WindowManager(state_manager)
    alert = NoSignalWindow(bus, state_manager)
    notice = FeedUpdateWindow(
        ConfigManager.get_config(), state_manager, surface.get_size()
    )
    window_manager.add_window(alert)
    window_manager.add_window(notice)

    if not notice.sprites:
        print(
            "[preview] the forged config is not stale, so there is no card to "
            "withdraw — pass --installed-version with a build the descriptor "
            "does not pin."
        )
        return

    alert.occludes_below = not args.no_arbitration
    reader = DemoReader()
    stale = False

    windows = (("NO SIGNAL", alert), ("feed card", notice))

    def state_line() -> str:
        """What is on screen, and — when they differ — what was overruled."""
        up = [name for name, w in windows if w.showing]
        withdrawn = [name for name, w in windows if w.visible and not w.showing]
        text = "showing " + (", ".join(up) if up else "dash only")
        if withdrawn:
            text += " / withdrawn " + ", ".join(withdrawn)
        return text

    def report(prefix: str) -> None:
        arb = "on" if alert.occludes_below else "OFF (overlapping)"
        print(
            f"[preview] {prefix}: link {'DEAD' if stale else 'live'}, "
            f"arbitration {arb} — {state_line()}"
        )

    if args.cycle:
        print(f"[preview] walking every {args.cycle:g}s — no keyboard needed")
    else:
        print("[preview] SPACE dead link, A arbitration, N re-arm the card, Q quits")

    display.present_full()

    clock = pygame.time.Clock()
    running = True
    elapsed = 0.0
    next_step = args.cycle or 0.0
    # Reported at the end of the frame, never at the keypress: `showing` is
    # only recomputed when the frame arbitrates, so printing on the toggle
    # would describe the new link state against last frame's answer.
    pending = "start"

    while running:
        dt = clock.tick(60) / 1000
        elapsed += dt

        if args.cycle and elapsed >= next_step:
            next_step += args.cycle
            # card -> card + alert -> recovery, then round again. Re-arming
            # reaches past dismiss() on purpose: the notice is deliberately
            # once-per-boot, and re-watching the transition is the point here.
            if not stale:
                stale = True
            else:
                stale = False
                notice._dismissed = False
            pending = "auto"

        if args.quit_after is not None and elapsed >= args.quit_after:
            running = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key == pygame.K_SPACE:
                    stale = not stale
                    pending = "link toggled"
                elif event.key == pygame.K_a:
                    alert.occludes_below = not alert.occludes_below
                    # The card's sprites went clean while it was withdrawn;
                    # the rising edge in its own update() re-dirties them.
                    state_manager.request_full_paint()
                    pending = "arbitration toggled"
                elif event.key == pygame.K_n:
                    notice._dismissed = False
                    pending = "card re-armed"
            else:
                # Through the compositor, so the withdrawn card's swallowing
                # (or not) of taps is what gets exercised.
                window_manager.handle_event(event)

        bus.update_frame(reader.latest())
        bus.merge_signals(
            {
                SignalKey.TELEMETRY_STALE: stale,
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

        if pending:
            report(pending)
            pending = None

    dashboard.exit()
    pygame.quit()


if __name__ == "__main__":
    main()
