"""Preview the "Connecting to Wi-Fi …" pill over a live dashboard.

On the appliance the pill (``WifiStatusWindow``) appears only on a
provisioned boot while wpa_supplicant is still associating — a state a dev
machine without wlan0 can never reach, and one that is gone within seconds
on a healthy network. This stands in for the Wi-Fi manager so the pill can
be judged on demand: its shape against the shared status pill, how it sits
over moving gauges, that it withdraws the moment the link is up (and the
base repaints behind it), and that the no-telemetry alert occludes it.

The dashboard underneath is live demo telemetry, so the withdrawal is
judged against moving gauges rather than a still.

Controls:

    A        associate — the pill withdraws for good, as on-device
    R        a fresh boot's association (brings the pill back)
    S        force / release telemetry_stale — the no-telemetry alert
             (SYSTEM_ALERT) must occlude the pill, not stack with it
    Esc / Q  quit

``--cycle`` needs no keyboard, which is what you want on the device: it
associates and re-boots the association on a timer so the panel walks
pill -> live -> pill on its own.

Usage (from the repo root, venv active):

    python tools/preview_wifi_connecting_pill.py
    python tools/preview_wifi_connecting_pill.py --cycle        # unattended
    python tools/preview_wifi_connecting_pill.py --associate-after 5
"""

import argparse
import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pygame  # noqa: E402


class StandInWifi:
    """Looks like WifiManager to WifiStatusWindow.

    Always has an interface and a healthy supplicant; association is
    flipped from the preview loop instead of by wpa_cli.
    """

    available = True

    def __init__(self):
        self._associated = threading.Event()

    def is_associated(self) -> bool:
        return self._associated.is_set()

    def ensure_supplicant(self) -> bool:
        return True

    def associate(self) -> None:
        self._associated.set()


def _write_config(path: Path) -> None:
    path.write_text(json.dumps({"telemetry_mode": "udp", "status_lights": False}))
    os.environ["IC_CONFIG_PATH"] = str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default="auto", help="display profile")
    parser.add_argument(
        "--associate-after",
        type=float,
        default=None,
        help="associate on a timer instead of the A key (for scripted runs)",
    )
    parser.add_argument(
        "--cycle",
        type=float,
        nargs="?",
        const=4.0,
        default=None,
        metavar="SECONDS",
        help="unattended: associate and re-boot every SECONDS (default 4)",
    )
    parser.add_argument(
        "--quit-after",
        type=float,
        default=None,
        help="exit after this many seconds (for scripted runs)",
    )
    args = parser.parse_args()

    _write_config(Path("/tmp/ic_preview_wifi_pill.json"))

    import instrument_cluster
    from instrument_cluster.core.plugin_system.plugin_manager import PluginManager
    from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus
    from instrument_cluster.peripherals.display import Display
    from instrument_cluster.signals.signal_keys import SignalKey
    from instrument_cluster.states.gate import build_dashboard
    from instrument_cluster.states.state_manager import StateManager
    from instrument_cluster.telemetry.demo import DemoReader
    from instrument_cluster.ui.no_signal_window import NoSignalWindow
    from instrument_cluster.ui.wifi_status_window import WifiStatusWindow
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

    # Through the compositor, exactly as main.py does — the pill is an
    # overlay window, so driving the state directly would never show it.
    # The alert rides along because occluding the pill is part of the
    # pill's contract worth eyeballing.
    window_manager = WindowManager(state_manager)
    window_manager.add_window(NoSignalWindow(bus, state_manager))

    wifi = StandInWifi()
    pill = WifiStatusWindow(wifi, state_manager)
    window_manager.add_window(pill)

    def reassociate() -> None:
        """A fresh boot's association.

        The window is deliberately one-shot — once associated it never
        returns — so a new round means a new window, exactly as a reboot
        would construct one. The spent instance is removed rather than
        left to pile up behind the compositor.
        """
        nonlocal wifi, pill
        window_manager._windows.remove(pill)
        wifi = StandInWifi()
        pill = WifiStatusWindow(wifi, state_manager)
        window_manager.add_window(pill)

    stale_forced = False
    reader = DemoReader()

    if args.cycle:
        print(f"[preview] cycling every {args.cycle:g}s — no keyboard needed")
    else:
        print("[preview] pill up — A associates, R re-boots, S forces the alert, Q quits")

    display.present_full()

    clock = pygame.time.Clock()
    running = True
    was_showing = None
    elapsed = 0.0
    next_cycle = args.cycle or 0.0

    while running:
        dt = clock.tick(60) / 1000
        elapsed += dt

        if args.cycle and elapsed >= next_cycle:
            next_cycle += args.cycle
            if wifi.is_associated():
                reassociate()
                print("[preview] fresh association (auto)")
            else:
                wifi.associate()
                print("[preview] associated (auto)")

        if args.associate_after is not None and elapsed >= args.associate_after:
            args.associate_after = None
            wifi.associate()
            print("[preview] associated (timer)")

        if args.quit_after is not None and elapsed >= args.quit_after:
            running = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key == pygame.K_a:
                    wifi.associate()
                    print("[preview] associated — pill should withdraw within ~1 s")
                elif event.key == pygame.K_r:
                    reassociate()
                    print("[preview] fresh association — pill back up")
                elif event.key == pygame.K_s:
                    stale_forced = not stale_forced
                    print(
                        "[preview] telemetry_stale forced — the alert must "
                        "occlude the pill"
                        if stale_forced
                        else "[preview] telemetry_stale released"
                    )
            window_manager.handle_event(event)

        bus.update_frame(reader.latest())
        bus.merge_signals(
            {
                SignalKey.TELEMETRY_STALE: stale_forced,
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

        showing = pill.showing
        if showing != was_showing:
            was_showing = showing
            print(f"[preview] pill {'SHOWING' if showing else 'withdrawn'}")

    dashboard.exit()
    pygame.quit()


if __name__ == "__main__":
    main()
