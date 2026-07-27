"""Preview the NO SIGNAL link-loss overlay against a real telemetry feed.

Unlike ``preview_delta_states.py`` (which forces ``telemetry_stale`` to
exercise the *rendering*), this drives the whole chain: a stand-in feed
program emits NDJSON to ``udp://127.0.0.1:5600``, the app's real
``SignalPipeline`` consumes it, and cutting the feed makes ``LinkSignal``
notice on its own. What you are checking is that the dash actually reports a
dead link — and, just as importantly, that it recovers and never cries wolf
during a pause.

The overlay you see here is therefore driven by the same code path a
sleeping console or a crashed feed would take.

Controls:

    SPACE   cut / restore the feed  (dash should go NO SIGNAL after ~1 s)
    P       toggle the paused flag  (grace extends to ~10 s, no NO SIGNAL)
    L       cut the feed *without* a paused flag, i.e. a hard link loss
    Esc / Q quit

``--cycle`` needs no keyboard at all, which is what you want on the device:
it drops and restores the feed on a timer so the panel walks live -> NO
SIGNAL -> live on its own.

Usage (from the repo root, venv active):

    python tools/preview_no_signal.py
    python tools/preview_no_signal.py --cycle          # unattended
    python tools/preview_no_signal.py --stale-after 2.0
"""

import argparse
import json
import math
import os
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pygame  # noqa: E402

LAP_SECONDS = 60.0
RADIUS_M = 500.0


class StandInFeed:
    """Sends TelemetryFrame NDJSON at 60 Hz, the way a real feed program does.

    ``live`` gates transmission so the link can be cut mid-session; ``paused``
    sets the flag GT7 reports when the game is paused, which LinkSignal treats
    as a legitimate reason for silence.
    """

    def __init__(self, host="127.0.0.1", port=5600, rate=60.0):
        from instrument_cluster.telemetry.demo import DemoReader

        self._reader = DemoReader()
        self._addr = (host, port)
        self._interval = 1.0 / rate
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._thread = None
        self._running = False
        self.live = True
        self.paused = False
        self.sent = 0

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        t0 = time.perf_counter()
        next_t = t0
        while self._running:
            now = time.perf_counter()
            if now < next_t:
                time.sleep(min(next_t - now, 0.005))
                continue
            next_t += self._interval
            if not self.live:
                continue
            self._sock.sendto(self._payload(now - t0), self._addr)
            self.sent += 1

    def _payload(self, t: float) -> bytes:
        # Strip explicit nulls: TelemetryFrame cannot round-trip its own dump
        # (fields typed `List[float] = None` reject null), and real feeds omit
        # channels they don't have. Note received_time is deliberately NOT
        # sent — the reader stamps it, which is what this preview relies on.
        obj = {
            k: v
            for k, v in json.loads(self._reader.latest().model_dump_json()).items()
            if v is not None and k != "received_time"
        }
        angle = 2.0 * math.pi * ((t % LAP_SECONDS) / LAP_SECONDS)
        obj["position"] = {
            "x": RADIUS_M * math.sin(angle),
            "y": 0.0,
            "z": RADIUS_M * math.cos(angle),
        }
        obj["lap_count"] = 2 + int(t // LAP_SECONDS)
        obj["current_lap_time"] = int((t % LAP_SECONDS) * 1000)
        obj["car_id"] = 1
        obj.setdefault("flags", {})
        obj["flags"]["car_on_track"] = True
        obj["flags"]["paused"] = self.paused
        return json.dumps(obj).encode("utf-8")

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._sock.close()


def _write_udp_config(path: Path) -> None:
    """Point the app at UDP mode before anything reads the config."""
    path.write_text(json.dumps({"telemetry_mode": "udp", "status_lights": False}))
    os.environ["IC_CONFIG_PATH"] = str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default="auto", help="display profile")
    parser.add_argument(
        "--stale-after",
        type=float,
        default=None,
        help="override LinkSignal's dead-link threshold in seconds (default 1.0)",
    )
    parser.add_argument(
        "--cycle",
        type=float,
        nargs="?",
        const=5.0,
        default=None,
        metavar="SECONDS",
        help="unattended: drop and restore the feed every SECONDS (default 5)",
    )
    parser.add_argument(
        "--quit-after",
        type=float,
        default=None,
        help="exit after this many seconds (for scripted runs)",
    )
    args = parser.parse_args()

    _write_udp_config(Path("/tmp/ic_preview_no_signal.json"))

    import instrument_cluster
    from instrument_cluster.core.plugin_system.plugin_manager import PluginManager
    from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus
    from instrument_cluster.peripherals.display import Display
    from instrument_cluster.signals.link_signal import LinkSignal
    from instrument_cluster.signals.signal_keys import SignalKey
    from instrument_cluster.signals.signal_pipeline import SignalPipeline
    from instrument_cluster.states.gate import build_dashboard
    from instrument_cluster.states.state_manager import StateManager
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

    # The dashboard *starts* the pipeline; this loop is what pumps it, exactly
    # as main.py does — so it has to be the same instance.
    pipeline = SignalPipeline()
    if args.stale_after is not None:
        pipeline.link = LinkSignal(stale_after_s=args.stale_after)

    dashboard = build_dashboard(
        state_manager, pipeline=pipeline, plugin_manager=plugin_manager
    )
    # Through the compositor, exactly as main.py does: the banner is a
    # SYSTEM_ALERT overlay window, not something the dashboard view paints,
    # so driving the state directly would never show it.
    state_manager.push_state(dashboard)
    window_manager = WindowManager(state_manager)
    window_manager.add_window(NoSignalWindow(bus, state_manager))

    feed = StandInFeed()
    feed.start()
    if args.cycle:
        print(f"[preview] cycling the feed every {args.cycle:g}s — no keyboard needed")
    else:
        print("[preview] feed LIVE — SPACE cuts it, P pauses, L hard-drops, Q quits")

    display.present_full()

    clock = pygame.time.Clock()
    running = True
    was_stale = None
    last_report = 0.0
    elapsed = 0.0
    next_cycle = args.cycle or 0.0

    while running:
        dt = clock.tick(60) / 1000
        elapsed += dt

        if args.cycle and elapsed >= next_cycle:
            next_cycle += args.cycle
            feed.live = not feed.live
            print(f"[preview] feed {'LIVE' if feed.live else 'CUT'} (auto)")

        if args.quit_after is not None and elapsed >= args.quit_after:
            running = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key == pygame.K_SPACE:
                    feed.live = not feed.live
                    print(f"[preview] feed {'LIVE' if feed.live else 'CUT'}")
                elif event.key == pygame.K_p:
                    feed.paused = not feed.paused
                    print(
                        f"[preview] paused flag {'ON' if feed.paused else 'OFF'}"
                        " — silence is now tolerated for ~10 s"
                        if feed.paused
                        else "[preview] paused flag OFF"
                    )
                elif event.key == pygame.K_l:
                    feed.paused = False
                    feed.live = False
                    print("[preview] hard link loss (no paused flag)")
            window_manager.handle_event(event)

        pipeline.update(bus, dt)
        plugin_manager.update(dt)
        window_manager.update(dt)
        display.present(window_manager.draw(surface))

        stale = bool(bus.signals.get(SignalKey.TELEMETRY_STALE))
        age = bus.signals.get(SignalKey.TELEMETRY_AGE_S) or 0.0
        if stale != was_stale:
            was_stale = stale
            print(
                f"[preview] telemetry_stale -> {stale}  (age {age:.2f}s, "
                f"{feed.sent} frames sent)"
            )
        last_report += dt
        if last_report >= 1.0:
            last_report = 0.0
            print(f"[preview]   age {age:5.2f}s  stale={stale}")

    feed.stop()
    dashboard.exit()
    pygame.quit()


if __name__ == "__main__":
    main()
