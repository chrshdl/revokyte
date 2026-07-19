from ..config import ConfigManager
from ..delta_calc import make_delta_calculator
from ..logger import Logger
from ..telemetry.mode import DiffReferenceMode
from ..telemetry.models import TelemetryFrame
from .signal_keys import SignalKey
from .stable_signal import StableSignal

# Partial-lap rejection thresholds.
# GT7 flying-start races place the rolling grid before the S/F line, so the
# first "lap" is only the grid-to-S/F segment (≈10-20 s). We discard any
# reference whose recorded duration or estimated circuit length falls below
# these limits.
_MIN_LAP_TIME_S = 20.0   # no real GT7 circuit completes in under 20 s
_MIN_REF_RATIO  = 0.6    # new reference must be ≥ 60 % of the longest seen

# The reference is resampled to uniform arc-length spacing, so its point count
# is a proxy for circuit length: length ≈ n_points * spacing. This MUST match
# DeltaCalculator(resample_spacing_m=...). If that default ever changes, change
# this too — the estimate drives the partial-lap rejection in _check_reference.
_REF_RESAMPLE_SPACING_M = 5.0


class DeltaSignal:
    def __init__(self):
        self.calculator = make_delta_calculator()
        self._last_diff_mode = None
        self._stable = StableSignal(refresh_period=0.2, hysteresis=0.02)
        self._last_current_lap_time_ms: int | None = None  # master clock, prev frame
        self._last_track_id = None
        self._last_confirmed_track_id = None  # last non-None track_id seen
        self._skip_first_reference: bool = False
        self._last_received_time: float = 0.0
        self._lap_timer: float = 0.0        # time driven in the current lap
        self._max_reference_length: float = 0.0  # longest accepted reference (m)
        self._ref_lap_time: float | None = None  # calculator clock time of the active reference lap
        self._last_ref_version = -1  # calculator ref_version at the last adopted lap
        self.logger = Logger(__class__.__name__).get()
        self._sync_configuration()

    def _sync_configuration(self):
        cfg = ConfigManager.get_config()
        current_mode = DiffReferenceMode(cfg.diff_reference_mode)
        if current_mode != self._last_diff_mode:
            self.calculator.use_fastest_reference_only = (
                current_mode == DiffReferenceMode.FASTEST
            )
            if self._last_diff_mode is not None:
                self._on_reference_mode_switched(current_mode)
            self._last_diff_mode = current_mode

    def _on_reference_mode_switched(self, mode: DiffReferenceMode) -> None:
        """A mid-session mode change swaps the calculator's active reference
        (it keeps previous-lap and fastest-lap trajectories side by side), so
        state derived from the reference's identity must refresh now — the
        usual refresh only runs at the next lap boundary."""
        ref_state = self._read_reference_state()
        self._ref_lap_time = ref_state.get("ref_lap_time") if ref_state else None
        # Let the swapped delta reach the display immediately instead of
        # holding the pre-switch value for the rest of the refresh period.
        self._stable.force_refresh()
        self.logger.info(
            f"[delta] diff reference mode switched to {mode.value!r}, "
            f"reference lap time now {self._ref_lap_time}"
        )

    def update(self, frame: TelemetryFrame, signals: dict, dt: float) -> dict:
        if frame is None or frame.flags is None:
            return {}

        # Native short-circuit: if the source already computed a delta, publish
        # it (through the same sample-and-hold display filter) instead of running
        # the GT7 trajectory calculator. Keyed on the data, never on the game —
        # a feed that provides its own delta (e.g. ACC) sets native_delta_ms;
        # GT7's feed leaves it None and falls through to the compute path below.
        native_delta_ms = getattr(frame, "native_delta_ms", None)
        if native_delta_ms is not None:
            raw_delta = native_delta_ms / 1000.0
            return {
                SignalKey.DELTA_DIFF: raw_delta,
                SignalKey.DELTA_DIFF_STABLE: self._stable.update(raw_delta, dt),
                SignalKey.DELTA_REF_LAP_TIME: None,
                SignalKey.DELTA_REFERENCE_MODE: None,
            }

        self._sync_configuration()

        lap_count = frame.lap_count or 0
        running = self._advance_lap_timer(frame, lap_count, dt)

        # Capture the master clock before processing so we can detect the lap
        # reset that drives the reference build inside calculator.process().
        prev_clt_ms = self._last_current_lap_time_ms
        current_clt_ms = frame.current_lap_time

        # Handle a track change BEFORE processing so its reset takes effect
        # this frame.
        self._handle_track_change(signals)

        raw_delta = self._process(frame, lap_count, running, dt)

        # Lap boundary = GT7's current_lap_time (master clock) resetting. That
        # is the frame the calculator promotes the finished lap to the
        # reference, so the bookkeeping below sees the freshly-built reference.
        # (lap_count ticks a frame or two earlier and must not drive this.)
        clock_reset = (
            current_clt_ms is not None
            and prev_clt_ms is not None
            and current_clt_ms < prev_clt_ms
        )
        if current_clt_ms is not None:
            self._last_current_lap_time_ms = current_clt_ms

        if clock_reset:
            raw_delta = self._on_lap_boundary(lap_count, raw_delta)

        return {
            SignalKey.DELTA_DIFF: raw_delta,
            SignalKey.DELTA_DIFF_STABLE: self._stable.update(raw_delta, dt),
            SignalKey.DELTA_REF_LAP_TIME: self._ref_lap_time,
            SignalKey.DELTA_REFERENCE_MODE: (
                self._last_diff_mode.value if self._last_diff_mode else None
            ),
        }

    def _advance_lap_timer(
        self, frame: TelemetryFrame, lap_count: int, dt: float
    ) -> bool:
        """Advance the current-lap timer and report whether the car is running.

        Detect a stale frame: GT7 stops sending UDP when paused, so the reader
        keeps returning the last received frame (same received_time). Treat a
        repeated received_time as paused so the lap timer does not drift.
        """
        frame_is_fresh = frame.received_time != self._last_received_time
        if frame_is_fresh:
            self._last_received_time = frame.received_time

        running = (
            frame_is_fresh
            and not frame.flags.paused
            and not frame.flags.loading_or_processing
            and lap_count > 0
        )
        if running:
            self._lap_timer += dt
        return running

    def _handle_track_change(self, signals: dict) -> None:
        # Always update _last_track_id (including to None) so that re-entering
        # the same circuit after leaving triggers full_reset(), not just
        # switching to a new circuit.
        track_id = signals.get(SignalKey.TRACK_ID)
        if track_id == self._last_track_id:
            return
        if track_id is not None:
            if track_id != self._last_confirmed_track_id:
                # Genuinely different circuit — discard the reference.
                self.logger.info(
                    f"Track changed {self._last_confirmed_track_id!r} → {track_id!r} "
                    f"({signals.get(SignalKey.TRACK_NAME)}), resetting delta reference"
                )
                self.calculator.full_reset()
                self._skip_first_reference = True
                self._max_reference_length = 0.0
                self._lap_timer = 0.0
                self._ref_lap_time = None
            else:
                # track_id went None (loading/retry) then came back to the same
                # circuit — preserve the reference.
                self.logger.info(
                    f"Track re-confirmed as {track_id!r} "
                    f"({signals.get(SignalKey.TRACK_NAME)}) after loading — "
                    f"keeping delta reference"
                )
            self._last_confirmed_track_id = track_id
        self._last_track_id = track_id

    def _process(
        self, frame: TelemetryFrame, lap_count: int, running: bool, dt: float
    ) -> float | None:
        pos = frame.position
        x = pos.x if pos is not None else 0.0
        y = pos.y if pos is not None else 0.0
        z = pos.z if pos is not None else 0.0
        return self.calculator.process(
            lap_index=lap_count,
            dt=dt,
            x=x,
            y=y,
            z=-z,
            running=running,
            gt7_lap_time_ms=frame.current_lap_time,
            gt7_last_lap_time_ms=frame.last_lap_time,
        )

    def _on_lap_boundary(self, lap_count: int, raw_delta: float | None) -> float | None:
        """Settle reference bookkeeping at the master-clock reset.

        Returns the delta to publish this frame — ``None`` when the just-built
        reference is discarded as a partial lap.
        """
        self._stable.reset()

        # lap_count has already ticked by the time the clock resets.
        finished_lap = lap_count - 1
        if finished_lap > 0:
            ref_state = self._read_reference_state()
            discard_reason = self._check_reference(finished_lap, ref_state)
            if discard_reason:
                self.logger.info(
                    f"[delta] discarding partial-lap reference: {discard_reason}"
                )
                self.calculator.full_reset()
                self._last_ref_version = -1
                self._ref_lap_time = None
                raw_delta = None
            else:
                self._adopt_reference(finished_lap, ref_state)

        self._lap_timer = 0.0
        self._skip_first_reference = False
        return raw_delta

    def _adopt_reference(self, finished_lap: int, ref_state: dict | None) -> None:
        """Refresh reference-derived state after a lap the calculator accepted."""
        new_ref_version = ref_state.get("ref_version", -1) if ref_state else -1
        if new_ref_version != self._last_ref_version:
            # Use the calculator's own reference time (traj.times[-1]) so both
            # sides of predicted = ref + delta are on the same calc-clock basis.
            # GT7's last_lap_time can exceed the calc clock by many seconds when
            # the reference lap contained pauses or loading screens (calc clock
            # pauses on non-running frames; GT7's timer does not), inflating the
            # prediction by the full pause duration.
            self._ref_lap_time = ref_state.get("ref_lap_time") if ref_state else None
            self._last_ref_version = new_ref_version
        else:
            # No new reference adopted. In FASTEST mode this is the normal "lap
            # wasn't quicker" case, but it also covers gated rejections
            # (implausibly fast, lap too short). Surface the calculator's reason
            # so it isn't a silent no-op that only a ref_version diff could
            # explain.
            reason = getattr(self.calculator, "last_reference_reject_reason", None)
            if reason:
                self.logger.info(
                    f"[delta] lap {finished_lap} not adopted as reference: {reason}"
                )

        ref_xs = ref_state.get("ref_xs") if ref_state else None
        if ref_xs is not None:
            self._max_reference_length = max(
                self._max_reference_length,
                len(ref_xs) * _REF_RESAMPLE_SPACING_M,
            )

    def _check_reference(self, completed_lap: int, ref_state: dict | None) -> str | None:
        """Return a reason string if the just-built reference should be discarded, else None."""
        if self._skip_first_reference:
            return f"lap {completed_lap} started mid-session after track detection"

        if self._lap_timer < _MIN_LAP_TIME_S:
            return f"lap {completed_lap} too short ({self._lap_timer:.1f}s < {_MIN_LAP_TIME_S:.0f}s — flying start?)"

        ref_xs = ref_state.get("ref_xs") if ref_state else None
        ref_len = len(ref_xs) * _REF_RESAMPLE_SPACING_M if ref_xs is not None else 0.0
        if (
            ref_len > 0
            and self._max_reference_length > 0
            and ref_len < _MIN_REF_RATIO * self._max_reference_length
        ):
            return (
                f"reference {ref_len:.0f}m < {_MIN_REF_RATIO:.0%} of "
                f"session max {self._max_reference_length:.0f}m"
            )

        return None

    def _read_reference_state(self) -> dict | None:
        """The calculator's reference introspection (ref_version, ref_lap_time,
        ref_xs), or None if unavailable."""
        try:
            return self.calculator.get_debug_state()
        except Exception:
            return None
