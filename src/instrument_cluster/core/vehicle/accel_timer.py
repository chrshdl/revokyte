"""Standing-start acceleration timing over a fixed distance.

The LED ladder's shift point is *computed* (see ``ecu.py``), so the question
of whether shifting on the ladder's last red actually gets the car down the
road faster than shifting when the game's own light comes on is settled by
driving both and comparing the clock. This is that clock: a 0-to-distance
timer that arms itself, starts on the launch and stops the instant the
target distance is reached, so the driver never touches the screen during a
run.

Two measurement choices worth stating, because both are load-bearing:

**Distance is integrated from speed, not read from position.**
``car_speed`` is the one channel every feed provides — ``position`` is
optional in the schema and absent on some — and the trapezoid over a 60 Hz
stream tracks a launch to well under a metre over 400 m.

**Time is measured on the receiving clock**, and ``received_time`` is used
only to tell a fresh frame from a held one. That field's *unit* varies by
reader (the demo reader stamps nanoseconds, the UDP reader monotonic
seconds), so it is a freshness marker here and nothing more. The cost is
that arrival jitter lands on the two endpoints of a run — about ±1 frame,
so ~±30 ms on a 12 s pull. That is well under the difference a shift
strategy makes, and, which is the point of an A/B test, it is not biased
toward either strategy.

A run is only ever *voided*, never fudged: a pause, a car change, a dropped
burst of frames or a car that rolls to a stop mid-run all discard the
attempt rather than publish a number the driver would compare against
another one measured differently.
"""

from __future__ import annotations

import math

# The distances the UI offers, and the only values the config accepts.
DISTANCES_M = (100, 200, 300, 400)
DEFAULT_DISTANCE_M = 400


class TimerState:
    NO_SIGNAL = "no_signal"  # no frames, or no car on track to time
    ROLLING = "rolling"  # moving; the car has to stop before a run can arm
    READY = "ready"  # stopped and armed, waiting for the launch
    RUNNING = "running"
    DONE = "done"  # target reached; the time stands until the next launch


class AccelTimer:
    """Feed it frames, read ``state`` / ``elapsed_s`` / ``distance_m``.

    Deliberately UI-free and clock-injected (``feed(frame, now)``), so the
    same code runs from the main loop and from a test that walks a
    synthetic pull one sample at a time.
    """

    # Speed thresholds, m/s. LAUNCH is the crossing that starts the clock;
    # ARM sits below it so a car creeping at the line cannot chatter between
    # armed and launched.
    LAUNCH_SPEED = 0.5  # 1.8 km/h — movement no idle jitter can fake
    ARM_SPEED = 0.3
    # A run that falls back to walking pace was aborted, not driven.
    ABORT_SPEED = 0.3
    # Longest gap between fresh frames the integration is trusted across.
    # Beyond it the last known speed would be standing in for a stretch of
    # road nobody measured, which silently invents distance — void the run
    # instead. Generous next to a 60 Hz feed (16 ms) on purpose: this fires
    # on a broken link, not on a slow one.
    MAX_GAP_S = 0.5

    def __init__(self, target_m: int = DEFAULT_DISTANCE_M):
        self.target_m = int(target_m)

        self.state = TimerState.NO_SIGNAL
        self.elapsed_s = 0.0
        self.distance_m = 0.0
        # Speed at the finish line, m/s — the other half of the comparison:
        # two strategies can reach 400 m together and leave differently.
        self.end_speed_ms = 0.0
        # Why the last run ended early, or None. Shown once, cleared by the
        # next launch or reset.
        self.note: str | None = None

        self._car_id: int | None = None
        self._last_received: float | None = None
        self._t: float | None = None  # receive time of the last fresh frame
        self._v = 0.0  # its speed
        self._t_start: float | None = None

    # ------------------------------------------------------------------
    # control
    # ------------------------------------------------------------------
    def set_target(self, meters: int) -> None:
        """Change the distance. A run in progress measured a different
        one, so it is discarded rather than re-scored."""
        meters = int(meters)
        if meters == self.target_m:
            return
        self.target_m = meters
        self.reset()

    def take_note(self) -> str | None:
        """Why the last run was voided, once — reading clears it.

        The consuming read is what keeps "a run was just voided" an *event*
        rather than a level: the caller decides how long the reason stays on
        screen, and a note it has already shown cannot re-arm itself. Same
        contract as ``AccelRunRecorder.take_result``.
        """
        note, self.note = self.note, None
        return note

    def reset(self) -> None:
        """Back to zero. The state is re-derived from the next fresh frame,
        so a reset with a live car standing still re-arms within a frame."""
        self.state = TimerState.NO_SIGNAL
        self.elapsed_s = 0.0
        self.distance_m = 0.0
        self.end_speed_ms = 0.0
        self.note = None
        self._t_start = None

    # ------------------------------------------------------------------
    # frame intake
    # ------------------------------------------------------------------
    def feed(self, frame, now: float) -> None:
        """One telemetry frame, with the receiver's monotonic clock.

        ``frame`` is None for "nothing live" — no frame yet, or a link the
        caller has already judged stale. Readers hold their last frame
        forever, so that judgement has to come from outside.
        """
        if frame is None:
            self._void(
                "waiting for telemetry", TimerState.NO_SIGNAL, keep_finished=True
            )
            self._t = None
            return

        if frame.received_time == self._last_received:
            return  # a held frame: paused, or the link has gone quiet
        self._last_received = frame.received_time

        flags = getattr(frame, "flags", None)
        if not getattr(flags, "car_on_track", False) or getattr(
            flags, "paused", False
        ):
            # Menus, a replay, a paused game: there is no car to time.
            self._void(
                "waiting for the car", TimerState.NO_SIGNAL, keep_finished=True
            )
            self._t = None
            return

        car_id = getattr(frame, "car_id", -1)
        if car_id != self._car_id:
            self._car_id = car_id
            self._void(None, TimerState.NO_SIGNAL)
            self._t = None

        v = max(0.0, float(getattr(frame, "car_speed", 0.0) or 0.0))
        t_prev, v_prev = self._t, self._v
        self._t, self._v = now, v

        if t_prev is None:
            # First frame of a session: no interval to integrate over yet,
            # but enough to say whether the car is stopped or rolling.
            self._settle(v)
            return

        dt = now - t_prev
        if dt <= 0.0:
            return
        if dt > self.MAX_GAP_S:
            self._void("signal lost", TimerState.NO_SIGNAL, keep_finished=True)
            self._settle(v)
            return

        if self.state == TimerState.RUNNING:
            self._advance(dt, v_prev, v)
        elif v > self.LAUNCH_SPEED and self.state == TimerState.READY:
            self._launch(dt, v_prev, v)
        else:
            self._settle(v)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _settle(self, v: float) -> None:
        """Pre-run bookkeeping: armed once stopped, disarmed once moving.

        A finished run re-arms the same way, so back-to-back pulls need no
        screen taps — the time on screen stands until the next launch
        actually starts.
        """
        if v <= self.ARM_SPEED:
            self.state = TimerState.READY
        elif v > self.LAUNCH_SPEED and self.state != TimerState.DONE:
            self.state = TimerState.ROLLING

    def _launch(self, dt: float, v_prev: float, v: float) -> None:
        """Start the clock at the sub-frame moment the car crossed
        ``LAUNCH_SPEED``, not at the frame that noticed it."""
        span = v - v_prev
        frac = (self.LAUNCH_SPEED - v_prev) / span if span > 0 else 0.0
        frac = min(1.0, max(0.0, frac))

        self._t_start = self._t - (1.0 - frac) * dt
        self.state = TimerState.RUNNING
        self.elapsed_s = 0.0
        self.end_speed_ms = 0.0
        self.note = None
        # Ground covered between the crossing and this frame.
        self.distance_m = 0.5 * (self.LAUNCH_SPEED + v) * (1.0 - frac) * dt

        if self.distance_m >= self.target_m:
            # Only reachable with an absurdly short target; finish honestly
            # rather than let the first frame overshoot it.
            self._finish(dt, self.LAUNCH_SPEED, v, from_dist=0.0)
        else:
            self.elapsed_s = self._t - self._t_start

    def _advance(self, dt: float, v_prev: float, v: float) -> None:
        segment = 0.5 * (v_prev + v) * dt
        if self.distance_m + segment >= self.target_m:
            self._finish(dt, v_prev, v, from_dist=self.distance_m)
            return

        self.distance_m += segment
        self.elapsed_s = self._t - self._t_start

        if v <= self.ABORT_SPEED:
            self._void("run stopped", TimerState.READY)

    def _finish(self, dt: float, v_prev: float, v: float, from_dist: float) -> None:
        """Stop on the target distance itself — solved inside the frame that
        crossed it, so the answer doesn't quantise to the frame rate."""
        tau = self._time_to_cover(self.target_m - from_dist, v_prev, v, dt)
        self.elapsed_s = (self._t - dt + tau) - self._t_start
        self.end_speed_ms = v_prev + (v - v_prev) * (tau / dt)
        self.distance_m = float(self.target_m)
        self.state = TimerState.DONE
        self.note = None

    @staticmethod
    def _time_to_cover(s: float, v0: float, v1: float, dt: float) -> float:
        """Time to cover ``s`` metres from ``v0``, taking the speed to change
        linearly to ``v1`` over ``dt`` — i.e. solve s = v0·t + ½·a·t²."""
        if s <= 0.0:
            return 0.0
        a = (v1 - v0) / dt
        if abs(a) < 1e-9:
            return min(dt, s / v0) if v0 > 0 else dt
        disc = v0 * v0 + 2.0 * a * s
        if disc < 0.0:
            return dt
        tau = (-v0 + math.sqrt(disc)) / a
        return min(dt, max(0.0, tau))

    def _void(self, note: str | None, state: str, keep_finished: bool = False) -> None:
        """Discard whatever was in flight.

        Only a run that was actually running leaves a note — nobody needs
        telling that a screen they just opened isn't timing anything.

        ``keep_finished`` spares a *completed* time: a link blip or a pause
        after the line says nothing about the run that already crossed it,
        and wiping the number the driver came here to read would be the
        rudest possible response to a dropped packet. A car change is the
        exception, and passes it as False — that time belongs to the other
        car.
        """
        if self.state == TimerState.DONE and keep_finished:
            self.state = state
            return
        if self.state == TimerState.RUNNING:
            self.note = note
        self.state = state
        self.elapsed_s = 0.0
        self.distance_m = 0.0
        self.end_speed_ms = 0.0
        self._t_start = None
