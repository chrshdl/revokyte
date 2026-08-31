"""Preview the Testing & Validation screen (the acceleration timer).

Runs the real ``AccelTestState`` against a synthetic car so every phase the
driver sees is a phase the state actually produced: waiting at the line,
armed, mid-run with the metres counting up, and the finished time with the
speed at the line.

The car is driven by a virtual clock, so a 400 m pull plays in whatever
time you ask for rather than in real time — which is also what lets the
headless screenshot below capture a *finished* run.

Usage (from the repo root, venv active):

    python tools/preview_accel_test.py                       # live, loops
    python tools/preview_accel_test.py --display waveshare_5
    python tools/preview_accel_test.py --phase done \\
        --shot /tmp/accel_done.png                           # headless PNG

``--phase`` picks where a screenshot is taken: ``waiting`` (no telemetry),
``ready``, ``running`` or ``done``. Interactive runs ignore it and cycle
through the lot; Esc/Q quits.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

PHASES = ("waiting", "ready", "running", "done")

# The synthetic car: a constant 5 m/s² pull, which reaches 400 m in ~12.6 s.
ACCEL = 5.0
HZ = 60.0


class _VirtualClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class _Car:
    """A car that waits at the line, launches, and rolls back to it."""

    def __init__(self, distance: int):
        self.distance = distance
        self.phase = "waiting"
        self.t_in_phase = 0.0
        self.speed = 0.0

    def step(self, dt: float, timer_state: str) -> None:
        self.t_in_phase += dt
        if self.phase == "waiting":  # no frames at all
            if self.t_in_phase > 1.5:
                self._to("ready")
        elif self.phase == "ready":  # stopped on the line, arming
            self.speed = 0.0
            if self.t_in_phase > 1.5:
                self._to("running")
        elif self.phase == "running":
            self.speed = ACCEL * self.t_in_phase
            if timer_state == "done":
                self._to("coasting")
        elif self.phase == "coasting":  # finished; back to the line
            self.speed = max(0.0, self.speed - 12.0 * dt)
            if self.speed <= 0.0 and self.t_in_phase > 4.0:
                self._to("ready")

    def _to(self, phase: str) -> None:
        self.phase = phase
        self.t_in_phase = 0.0
        if phase != "coasting":
            self.speed = 0.0

    @property
    def live(self) -> bool:
        return self.phase != "waiting"


def _write_config(path: Path, distance: int) -> None:
    path.write_text(json.dumps({"telemetry_mode": "demo", "accel_test_distance": distance}))
    os.environ["IC_CONFIG_PATH"] = str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default="dev", help="display profile")
    parser.add_argument(
        "--distance", type=int, default=400, choices=[100, 200, 300, 400]
    )
    parser.add_argument("--phase", default="done", choices=PHASES)
    parser.add_argument(
        "--shot", default=None, help="save a PNG of --phase here and exit (headless)"
    )
    parser.add_argument(
        "--speed", type=float, default=4.0, help="virtual seconds per real second"
    )
    args = parser.parse_args()

    if args.shot:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

    _write_config(Path("/tmp/ic_preview_accel.json"), args.distance)

    import pygame

    from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus
    from instrument_cluster.peripherals.display import Display
    from instrument_cluster.states.accel_test_state import AccelTestState
    from instrument_cluster.states.state_manager import StateManager
    from instrument_cluster.telemetry.models import Flags, TelemetryFrame
    from instrument_cluster.ui.views.registry import core_views, views

    pygame.init()
    display = Display(args.display)
    views.preload(core_views())

    bus = VehicleBus()
    manager = StateManager(display.surface, bus)
    clock = _VirtualClock()
    state = AccelTestState(manager)
    state._clock = clock
    manager.push_state(state)

    car = _Car(args.distance)
    step = 1 / HZ
    frames_wanted = None if args.shot is None else 60 * 60 * 5  # a generous cap

    pygame_clock = pygame.time.Clock()
    running = True
    frames = 0
    while running:
        if args.shot:
            dt = step
        else:
            dt = pygame_clock.tick(60) / 1000 * args.speed

        car.step(dt, state.timer.state)
        clock.t += dt
        bus.frame = (
            TelemetryFrame(
                car_id=1461,
                received_time=clock.t,
                car_speed=car.speed,
                flags=Flags(car_on_track=True),
            )
            if car.live
            else None
        )

        manager.update(dt)
        display.present(manager.draw(display.surface))

        if args.shot:
            frames += 1
            if _matches(args.phase, car, state) or frames > frames_wanted:
                pygame.image.save(display.surface, args.shot)
                print(f"saved {args.shot} ({args.phase})")
                break
            continue

        for event in pygame.event.get():
            if event.type == pygame.QUIT or (
                event.type == pygame.KEYDOWN
                and event.key in (pygame.K_ESCAPE, pygame.K_q)
            ):
                running = False
            manager.handle_event(event)

    pygame.quit()


def _matches(phase: str, car, state) -> bool:
    """Whether the screen is showing the phase the screenshot asked for.

    Read off the *timer*, not the fake car: the point of a preview is to
    catch the state disagreeing with what the driver is doing.
    """
    from instrument_cluster.core.vehicle.accel_timer import TimerState

    wanted = {
        "waiting": TimerState.NO_SIGNAL,
        "ready": TimerState.READY,
        "running": TimerState.RUNNING,
        "done": TimerState.DONE,
    }[phase]
    if wanted == TimerState.RUNNING:
        # Half way down the road, so the metres counter has something to say.
        return state.timer.state == wanted and state.timer.distance_m > (
            state.timer.target_m / 2
        )
    return state.timer.state == wanted


if __name__ == "__main__":
    main()
