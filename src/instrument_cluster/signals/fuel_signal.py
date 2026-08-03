from collections import deque

from ..logger import Logger
from ..telemetry.models import TelemetryFrame
from .fuel_flow import FuelFlowObserver
from .signal_keys import SignalKey


class FuelSignal:
    """Per-lap fuel consumption and laps-remaining estimate.

    Publishes:
    - ``fuel_per_lap``       — the last valid completed lap's consumption
                               (GT7 gas units, not liters).
    - ``fuel_used_current_lap`` — fuel burned so far in the lap in progress:
                               anchored to measured gas_level at every
                               ``_LIVE_REFRESH_S`` refresh and filled in
                               between by the engine model's fuel flow
                               (when a calibrated map is live), so the
                               readout climbs smoothly and snaps back to
                               truth on each refresh.
    - ``fuel_laps_remaining``— gas_level divided by the rolling average of
                               the last ``_WINDOW`` completed laps.
    - ``fuel_rate``          — instantaneous model burn in game units/s;
                               None whenever the model is inert.

    Measured telemetry stays ground truth: the FuelFlowObserver only
    interpolates between its samples and rescales itself against every
    real gas_level drop. With no engine map (unknown car, ACC, missing
    artifact) every published value is exactly what it was before the
    observer existed.

    The completed-lap values are None until a full green-flag lap has been
    observed; all are None while fuel data is meaningless (EVs, fuel
    consumption disabled).
    """

    def __init__(
        self,
        window=3,
        refuel_eps=0.05,
        min_lap_consumption=0.01,
        live_refresh_s=3.0,
        flow_observer: FuelFlowObserver | None = None,
    ):
        self.logger = Logger(__class__.__name__).get()

        # Model-based rate between measured anchors; injected in tests.
        self._flow = flow_observer if flow_observer is not None else FuelFlowObserver()

        # Rolling window of completed-lap consumptions the
        # laps-remaining estimate averages over.
        self.window = window
        # A gas_level rise above this between frames is a pit
        # refuel. The lap in progress is tainted and must not
        # produce a (negative) consumption sample.
        self.refuel_eps = refuel_eps
        # A completed lap consuming less than this means fuel
        # consumption is disabled in the session (time trial,
        # lobby setting), nothing meaningful to estimate.
        self.min_lap_consumption = min_lap_consumption
        # Refresh cadence of the live current-lap consumption
        # readout. Sample-and-hold keeps the widget calm.
        self.live_refresh_s = live_refresh_s

        self._samples: deque[float] = deque(maxlen=window)

        # Running sum of _samples, maintained incrementally on append/evict
        # so the per-frame average is O(1) instead of re-summing the window.
        self._samples_sum: float = 0.0

        self._lap_start_fuel: float | None = None

        # The first observed lap is partial (joined mid-lap,
        # out-lap, grid segment), never bank it.
        # Exception: a race start seen live (lap_count 0 -> 1)
        # arms lap 1 directly.
        self._lap_valid: bool = False
        # Live current-lap consumption, sample-and-hold. None means "sample
        # on the next fresh frame" (startup, refuel rebase, resets).
        self._live_used: float | None = None
        self._live_timer: float = 0.0
        self._prev_gas_level: float | None = None
        self._last_current_lap_time_ms: int | None = None
        self._last_lap_count: int | None = None
        self._last_received_time: float = 0.0
        self._last_track_id = None
        self._last_confirmed_track_id = None
        self._last_output: dict = {}

    def _reset_lap_tracking(self) -> None:
        self._samples.clear()
        self._samples_sum = 0.0
        self._lap_start_fuel = None
        self._lap_valid = False
        self._live_used = None
        self._live_timer = 0.0

    def _bank_sample(self, fuel_used: float) -> None:
        # The deque is the circular buffer: at maxlen, append() evicts the
        # oldest sample, so subtract it from the running sum first.
        if len(self._samples) == self.window:
            self._samples_sum -= self._samples[0]
        self._samples_sum += fuel_used
        self._samples.append(fuel_used)

    def update(self, frame: TelemetryFrame, signals: dict, dt: float) -> dict:
        if frame is None:
            return {}

        # EVs (and frames without fuel data) report capacity 0 — publish
        # explicit Nones so a car swap clears stale values off the bus. The
        # UDP reader's pre-connection default frame lands here too, which is
        # what clears DemoFuelSignal's values after a demo → UDP switch.
        if frame.gas_capacity <= 0.0:
            self._reset_lap_tracking()
            self._prev_gas_level = None
            return self._publish(None, None, None)

        # No UDP when paused, so the reader keeps returning the last frame
        # (same received_time) — nothing has advanced.
        if frame.received_time == self._last_received_time:
            return self._last_output
        self._last_received_time = frame.received_time

        self._handle_track_change(signals.get(SignalKey.TRACK_ID))

        gas_level = frame.gas_level

        # Session restart drops lap_count: the fuel load likely changed on the
        # grid, and the same frame usually carries the lap-clock reset too.
        # Reset here so the boundary below is swallowed and the post-restart
        # out-lap is not promoted to a valid lap.
        restarted = self._is_restart(frame.lap_count)
        if restarted:
            self._reset_lap_tracking()
            self._flow.freeze_observation()

        self._handle_refuel(gas_level)

        # Integrate the model rate for this live frame before any anchor
        # rebase below, so an anchor always matches the current integral.
        self._flow.update(frame, dt)

        if self._is_lap_boundary(frame) and not restarted:
            self._close_lap(gas_level)
            self._open_lap(gas_level)

        # First frame ever (or just after a reset): anchor the live readout to
        # the current level so it reads 0.0 rather than blank.
        if self._lap_start_fuel is None:
            self._lap_start_fuel = gas_level

        self._update_live_used(gas_level, dt)
        self._remember(frame)

        return self._build_output(gas_level)

    def _handle_track_change(self, track_id) -> None:
        # A loading blip (id -> None -> same id) must not discard the lap
        # history: only a genuinely different confirmed track resets it.
        if track_id == self._last_track_id:
            return
        if track_id is not None:
            if track_id != self._last_confirmed_track_id:
                self.logger.info(
                    f"Track changed {self._last_confirmed_track_id!r} -> "
                    f"{track_id!r}, resetting fuel history"
                )
                self._reset_lap_tracking()
            self._last_confirmed_track_id = track_id
        self._last_track_id = track_id

    def _is_restart(self, lap_count) -> bool:
        return (
            lap_count is not None
            and self._last_lap_count is not None
            and lap_count < self._last_lap_count
        )

    def _handle_refuel(self, gas_level: float) -> None:
        # A gas_level rise beyond the noise floor is a pit refuel. Rebase so
        # laps-remaining tracks the new level immediately; the tainted lap is
        # discarded at the next boundary via _lap_valid, and re-sampling the
        # live readout (None) snaps it back to 0.0 against the rebased level.
        if (
            self._prev_gas_level is not None
            and gas_level > self._prev_gas_level + self.refuel_eps
        ):
            self._lap_valid = False
            self._lap_start_fuel = gas_level
            self._live_used = None
            self._flow.freeze_observation()

    def _is_lap_boundary(self, frame: TelemetryFrame) -> bool:
        lap_count = frame.lap_count
        current_clt_ms = frame.current_lap_time

        # Primary: GT7's current_lap_time (master clock) resetting, as in
        # DeltaSignal.
        clock_reset = (
            current_clt_ms is not None
            and self._last_current_lap_time_ms is not None
            and current_clt_ms < self._last_current_lap_time_ms
        )
        # Fallback for sources without the clock (Packet A): the lap_count
        # tick — fuel doesn't need the exact S/F frame, so the tick's 1-2
        # frame skew is harmless. Requires a previous racing lap (> 0) so a
        # rolling start's grid-to-line segment is never promoted.
        lap_tick = (
            current_clt_ms is None
            and lap_count is not None
            and self._last_lap_count is not None
            and self._last_lap_count > 0
            and lap_count == self._last_lap_count + 1
        )
        # Race start: lap_count ticking 0 -> 1 is the green light on a standing
        # start (the line crossing on a rolling one), so the whole first lap is
        # in view — arm it directly instead of waiting for the first line
        # crossing. The launch makes the sample slightly atypical, but the
        # estimate arrives a lap earlier.
        race_start = lap_count == 1 and self._last_lap_count == 0

        return clock_reset or lap_tick or race_start

    def _close_lap(self, gas_level: float) -> None:
        """Bank the lap just completed, if it was a valid green-flag lap."""
        if not (self._lap_valid and self._lap_start_fuel is not None):
            return
        fuel_used = self._lap_start_fuel - gas_level
        if fuel_used > self.min_lap_consumption:
            self._bank_sample(fuel_used)
        else:
            # A full lap with ~zero consumption: fuel use is disabled in this
            # session — drop the history so the estimate reverts to the
            # placeholder.
            self._samples.clear()
            self._samples_sum = 0.0

    def _open_lap(self, gas_level: float) -> None:
        """Arm tracking for the new lap; the live readout restarts at zero."""
        self._lap_start_fuel = gas_level
        self._lap_valid = True
        self._live_used = 0.0
        self._live_timer = 0.0
        self._flow.rebase_anchor()

    def _update_live_used(self, gas_level: float, dt: float) -> None:
        # Live current-lap consumption, refreshed every live_refresh_s of
        # driving time. Stale (paused) frames return early in update(), so the
        # timer only advances while the session is live. A None samples
        # immediately so startup and rebases never leave the widget blank.
        # Every measured sample re-anchors the model integral: between
        # refreshes the published value climbs by the model, at each
        # refresh it snaps back to measured truth.
        self._live_timer += dt
        if self._live_used is None or self._live_timer >= self.live_refresh_s:
            self._live_timer = 0.0
            self._live_used = max(0.0, self._lap_start_fuel - gas_level)
            self._flow.rebase_anchor()

    def _remember(self, frame: TelemetryFrame) -> None:
        if frame.current_lap_time is not None:
            self._last_current_lap_time_ms = frame.current_lap_time
        if frame.lap_count is not None:
            self._last_lap_count = frame.lap_count
        self._prev_gas_level = frame.gas_level

    def _build_output(self, gas_level: float) -> dict:
        avg = self._samples_sum / len(self._samples) if self._samples else None
        live_used = self._live_used
        if live_used is not None and self._flow.active:
            live_used = live_used + self._flow.units_since_anchor()
        return self._publish(
            fuel_per_lap=self._samples[-1] if self._samples else None,
            fuel_used_current_lap=live_used,
            fuel_laps_remaining=(
                gas_level / avg if avg is not None and avg > 1e-6 else None
            ),
            fuel_rate=self._flow.rate_units_s(),
        )

    def _publish(
        self, fuel_per_lap, fuel_used_current_lap, fuel_laps_remaining,
        fuel_rate=None,
    ) -> dict:
        self._last_output = {
            SignalKey.FUEL_PER_LAP: fuel_per_lap,
            SignalKey.FUEL_USED_CURRENT_LAP: fuel_used_current_lap,
            SignalKey.FUEL_LAPS_REMAINING: fuel_laps_remaining,
            SignalKey.FUEL_RATE: fuel_rate,
        }
        return self._last_output
