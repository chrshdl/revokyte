"""Testing & Validation: drives the standing-start acceleration timer.

The measurement itself is ``core/vehicle/accel_timer.py``; this state is the
wiring — it feeds the timer the bus's frames, translates its state into the
words on screen, and owns the two controls.

It reads the bus but never touches the pipeline: the dashboard is only
*paused* under this screen, so the main loop keeps pumping telemetry (that
is the whole point of the pipeline living in the loop rather than in
DashboardState). A run therefore keeps timing while this screen is open, and
nothing about opening it disturbs the delta or track signals.
"""

from __future__ import annotations

import time

from ..config import ConfigManager
from ..core.vehicle.accel_timer import AccelTimer, TimerState
from ..logger import Logger
from ..states.state_manager import StateManager
from ..ui.colors import Color
from ..ui.events import (
    ACCEL_DISTANCE_SELECTED,
    ACCEL_RESET_RELEASED,
    BUTTON_BACK_RELEASED,
)
from ..ui.views.accel_test_view import AccelTestView
from .state import State


class AccelTestState(State):
    # How long "why the last run was voided" stays on the status line before
    # it gives way to what the timer is doing now. Long enough to read from
    # a moving car, short enough that it never masks a fresh Ready.
    NOTE_HOLD_S = 4.0

    # The receive clock the timer measures on. A seam, not a setting: the
    # preview tool and the state tests replace it to walk a synthetic pull
    # faster than real time. Nothing in the app ever reassigns it.
    _clock = staticmethod(time.monotonic)

    view_class = AccelTestView

    def __init__(self, state_manager: StateManager | None = None):
        super().__init__(state_manager)
        self.logger = Logger(__class__.__name__).get()

        self.bus = getattr(state_manager, "vehicle_bus", None)
        self.timer = AccelTimer(ConfigManager.get_config().accel_test_distance)
        # The voided-run note currently on screen, and how long it has been.
        self._note: str | None = None
        self._note_age_s = 0.0

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def enter(self, screen):
        # A visit starts at zero. The state is rebuilt per visit anyway;
        # this also covers a re-entry that reused the instance.
        self.timer.set_target(ConfigManager.get_config().accel_test_distance)
        self.timer.reset()
        self._note = None
        return super().enter(screen)

    def exit(self):
        # The distance was applied in-memory as it was chosen (the timer
        # needs it live); queue the disk write on the way out, like Setup.
        ConfigManager.persist()
        super().exit()

    def update(self, dt):
        super().update(dt)
        if self.view is None:
            # The registry failed to build the screen (a defective image;
            # see core/system/unhealthy.py). Timing into nothing would only
            # fill the journal with one traceback per frame.
            return

        self.timer.feed(self._live_frame(), self._clock())
        self._age_note(dt)

        self.view.set_readout(self.timer.elapsed_s)
        text, color = self._status()
        self.view.set_status(text, color)

        self.view.update(dt)

    def _age_note(self, dt: float) -> None:
        """Latch a newly voided run's reason, and let it expire."""
        note = self.timer.take_note()
        if note is not None:
            self._note, self._note_age_s = note, 0.0
            self.logger.info("accel run voided: %s", note)
            return
        if self._note is None:
            return
        self._note_age_s += dt
        # A launch supersedes the note outright — the driver is answering it.
        running = self.timer.state == TimerState.RUNNING
        if running or self._note_age_s >= self.NOTE_HOLD_S:
            self._note = None

    def _live_frame(self):
        """The frame to time on, or None when there is nothing live.

        Readers hold their last frame forever, so a dead link looks exactly
        like a stationary car unless ``telemetry_stale`` is consulted — and
        a stationary car is precisely the state this screen arms in.
        """
        if self.bus is None or self.bus.frame is None:
            return None
        if self.bus.signals.get("telemetry_stale"):
            return None
        return self.bus.frame

    # ------------------------------------------------------------------
    # readout
    # ------------------------------------------------------------------
    def _status(self) -> tuple[str, tuple[int, int, int] | None]:
        timer = self.timer
        if self._note is not None:
            return f"Run voided — {self._note}", Color.LIGHTEST_RED.rgb()

        if timer.state == TimerState.NO_SIGNAL:
            return "Waiting for telemetry", None
        if timer.state == TimerState.ROLLING:
            return "Come to a stop to arm", None
        if timer.state == TimerState.READY:
            return f"Ready — launch for {timer.target_m} m", Color.LIGHT_GREEN.rgb()
        if timer.state == TimerState.RUNNING:
            return f"{timer.distance_m:.0f} / {timer.target_m} m", Color.WHITE.rgb()
        # DONE: the terminal speed is the other half of the comparison —
        # two runs can reach the line together and leave it differently.
        return (
            f"{timer.target_m} m at {timer.end_speed_ms * 3.6:.0f} km/h",
            Color.LIGHT_GREEN.rgb(),
        )

    # ------------------------------------------------------------------
    # input
    # ------------------------------------------------------------------
    def handle_event(self, event):
        if self.view.handle_event(event):
            return True

        if event.type == BUTTON_BACK_RELEASED:
            self.state_manager.pop_state()
            return True

        if event.type == ACCEL_DISTANCE_SELECTED:
            # Applied live (a run in progress measured the old distance and
            # is discarded by set_target); the disk write waits for exit().
            ConfigManager.set_accel_test_distance(event.mode, persist=False)
            self.timer.set_target(event.mode)
            return True

        if event.type == ACCEL_RESET_RELEASED:
            self.timer.reset()
            self._note = None
            return True

        return False
