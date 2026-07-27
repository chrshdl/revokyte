"""Preview the delta gauge's empty states (BEACON / REF LAP / NO REF).

Renders the real dashboard — actual plugins, actual DashboardView, actual
dirty-rect draw path — with demo telemetry underneath, but with the delta
signals forced so every state can be inspected on demand instead of waiting
three laps for one to occur naturally.

Runs on a desktop window and, unchanged, on the device's own panel (the
display profile is resolved the same way the app resolves it), which is the
only place the state words' legibility can really be judged.

Controls:

    SPACE / RIGHT   cycle: armed -> BEACON -> REF LAP -> NO REF
    +  /  -         resize the state word live (to trial a size on-panel)
    Esc / Q         quit

The NO SIGNAL alert is not here: it is a SYSTEM_ALERT overlay window
composited by the WindowManager, so it needs the real compositor rather than
a forced signal. See ``preview_no_signal.py``.

Usage (from the repo root, venv active):

    python tools/preview_delta_states.py
    python tools/preview_delta_states.py --state ref_lap
    python tools/preview_delta_states.py --font-size 52
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pygame  # noqa: E402

import instrument_cluster  # noqa: E402
from instrument_cluster.core.plugin_system.plugin_manager import (  # noqa: E402
    PluginManager,
)
from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus  # noqa: E402
from instrument_cluster.peripherals.display import Display  # noqa: E402
from instrument_cluster.signals.signal_keys import DeltaState, SignalKey  # noqa: E402
from instrument_cluster.states.gate import build_dashboard  # noqa: E402
from instrument_cluster.states.state_manager import StateManager  # noqa: E402
from instrument_cluster.telemetry.demo import DemoReader  # noqa: E402
from instrument_cluster.ui.utils import load_font  # noqa: E402
from instrument_cluster.ui.widgets.delta_time_widget import (  # noqa: E402
    _STATE_FONT_FAMILY,
    _STATE_FONT_SIZE,
    DeltaTimeWidget,
)

# armed (a real number) plus every reason the gauge can have no number.
_CYCLE = [None, DeltaState.BEACON, DeltaState.REF_LAP, DeltaState.NO_REF]
_LABELS = {
    None: "armed (numeric delta)",
    DeltaState.BEACON: "BEACON  — not in a timed lap",
    DeltaState.REF_LAP: "REF LAP — recording the first reference",
    DeltaState.NO_REF: "NO REF  — an established reference was discarded",
}


def _delta_widget(plugin_manager) -> DeltaTimeWidget | None:
    for plugin in plugin_manager.plugins:
        for sprite in getattr(plugin, "sprites", []) or []:
            if isinstance(sprite, DeltaTimeWidget):
                return sprite
    return None


def _set_state_font(widget: DeltaTimeWidget, size: int) -> None:
    """Swap the state word's face.

    Invalidating _last_value_str is enough to force the repaint: the next
    frame's set_state() sees a mismatch and re-renders whatever word is up.
    """
    if widget is None:
        return
    widget._state_font = load_font(size=size, family=_STATE_FONT_FAMILY)
    widget._last_value_str = None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state",
        choices=["armed", "beacon", "ref_lap", "no_ref"],
        default="ref_lap",
        help="delta state to start on (default: ref_lap)",
    )
    parser.add_argument(
        "--font-size",
        type=int,
        default=None,
        help=f"override the state word's design-px size (default: {_STATE_FONT_SIZE})",
    )
    parser.add_argument(
        "--display",
        default="auto",
        help="display profile: auto (default), dev, …",
    )
    args = parser.parse_args()

    # Keep a preview run from touching the real device config.
    os.environ.setdefault("IC_CONFIG_PATH", "/tmp/ic_preview_delta.json")

    pygame.init()
    display = Display(args.display)
    surface = display.surface

    bus = VehicleBus()
    state_manager = StateManager(surface, bus)
    plugin_dir = os.path.join(
        os.path.dirname(instrument_cluster.__file__), "plugins"
    )
    plugin_manager = PluginManager(plugin_dir, bus)
    plugin_manager.load_plugins()
    state_manager.plugin_manager = plugin_manager

    dashboard = build_dashboard(state_manager, plugin_manager=plugin_manager)
    dashboard.enter(surface)

    widget = _delta_widget(plugin_manager)
    if args.font_size:
        _set_state_font(widget, args.font_size)
    font_size = args.font_size or _STATE_FONT_SIZE

    reader = DemoReader()
    reader.start()

    index = {"armed": 0, "beacon": 1, "ref_lap": 2, "no_ref": 3}[args.state]
    print(f"[preview] {_LABELS[_CYCLE[index]]}")

    # enter() already built the state's background surface.
    dashboard.full_paint(surface)
    display.present_full()

    clock = pygame.time.Clock()
    running = True
    while running:
        dt = clock.tick(60) / 1000

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key in (pygame.K_SPACE, pygame.K_RIGHT):
                    index = (index + 1) % len(_CYCLE)
                    print(f"[preview] {_LABELS[_CYCLE[index]]}")
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS):
                    font_size += 2
                    _set_state_font(widget, font_size)
                    print(f"[preview] state font size {font_size}")
                elif event.key == pygame.K_MINUS:
                    font_size = max(8, font_size - 2)
                    _set_state_font(widget, font_size)
                    print(f"[preview] state font size {font_size}")
            dashboard.handle_event(event)

        state = _CYCLE[index]
        bus.update_frame(reader.latest())
        bus.merge_signals(
            {
                SignalKey.DELTA_STATE: state,
                # Armed shows a live-looking number; every other state must
                # have none, which is what makes the word appear.
                SignalKey.DELTA_DIFF_STABLE: -0.42 if state is None else None,
                SignalKey.DELTA_REFERENCE_MODE: "fastest",
                SignalKey.TRACK_NAME: "Spa-Francorchamps",
                SignalKey.FUEL_LAPS_REMAINING: 12.4,
                SignalKey.FUEL_USED_CURRENT_LAP: 1.2,
            }
        )

        plugin_manager.update(dt)
        dashboard.update(dt)
        display.present(dashboard.draw(surface))

    dashboard.exit()
    pygame.quit()


if __name__ == "__main__":
    main()
