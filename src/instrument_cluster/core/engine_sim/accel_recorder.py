"""Full-throttle acceleration run capture, for validating the engine model.

cars.json only pins two points per car; GT7's real torque curve *shape*
is recoverable empirically from a full-throttle pull — rpm and speed over
time in a fixed gear give the wheel-force curve directly (shift points
depend only on that shape, so no mass or drag constant is needed for a
useful comparison; see tools/engine_sim/analyze_accel.py).

``AccelRunRecorder`` watches live frames and captures runs automatically:
it arms whenever a live car is on telemetry, starts a run when the pedal
hits the floor in a forward gear, samples every fresh frame, and ends the
run on a lift, an upshift, or the rev limiter. Quality gates decide
whether the run is worth keeping; accepted runs are written as JSON by
``AccelRunStore``. The recorder is UI-free and fully deterministic —
the accel-logger view only renders its state.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from ...telemetry.units import ThrottleNormalizer

# Run detection thresholds.
_THROTTLE_ON = 0.95  # pedal at least this far down starts/continues a run
_THROTTLE_OFF = 0.90  # falling below this ends the run (hysteresis)
# An rpm drop this far below the run's maximum means limiter bounce or an
# ignition cut — the pull is over even though the pedal is still down.
_RPM_DROP_END = 300.0

# Quality gates for keeping a run.
_MIN_DURATION_S = 1.5
_MIN_RPM_SPAN = 1500.0
_MIN_SAMPLES = 30

_SCHEMA_VERSION = 1


class RecorderState:
    IDLE = "idle"  # no live car on telemetry
    ARMED = "armed"  # waiting for a full-throttle pull
    RECORDING = "recording"


@dataclass(frozen=True)
class RunResult:
    accepted: bool
    reason: str  # end trigger (accepted) or rejection cause
    path: Path | None = None
    gear: int = 0
    rpm_lo: float = 0.0
    rpm_hi: float = 0.0
    sample_count: int = 0


def default_runs_dir() -> Path:
    """Sibling of the config file — the one directory the app already
    guarantees is writable on every platform (incl. the appliance)."""
    config_path = Path(
        os.environ.get(
            "IC_CONFIG_PATH",
            Path.home() / ".config" / "instrument-cluster" / "config.json",
        )
    )
    return config_path.parent / "accel_runs"


class AccelRunStore:
    """One JSON file per accepted run, grouped by car id."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def _car_dir(self, car_id: int) -> Path:
        return self.base_dir / f"car_{car_id}"

    def count_for(self, car_id: int) -> int:
        car_dir = self._car_dir(car_id)
        if not car_dir.is_dir():
            return 0
        return len(list(car_dir.glob("run_*.json")))

    def save(self, header: dict, samples: list[dict]) -> Path:
        car_dir = self._car_dir(header["car_id"])
        car_dir.mkdir(parents=True, exist_ok=True)
        index = self.count_for(header["car_id"]) + 1
        path = car_dir / (
            f"run_{index:03d}_g{header['gear']}_"
            f"{int(header['rpm_lo'])}-{int(header['rpm_hi'])}.json"
        )
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"header": header, "samples": samples}, f)
        return path


class AccelRunRecorder:
    def __init__(self, store: AccelRunStore):
        self.store = store
        self.state = RecorderState.IDLE
        self.last_result: RunResult | None = None

        self._normalizer = ThrottleNormalizer()
        self._last_received: float | None = None
        self._car_id: int | None = None
        self._gear = 0
        self._gear_ratio: float | None = None
        self._samples: list[dict] = []
        self._rpm_hi = 0.0

    # -- live info for the view --

    @property
    def car_id(self) -> int | None:
        return self._car_id

    @property
    def run_rpm_span(self) -> float:
        """rpm covered by the run in progress (0 outside a run)."""
        if self.state != RecorderState.RECORDING or not self._samples:
            return 0.0
        return max(0.0, self._rpm_hi - self._samples[0]["rpm"])

    @property
    def run_duration_s(self) -> float:
        if self.state != RecorderState.RECORDING or len(self._samples) < 2:
            return 0.0
        return self._samples[-1]["t"] - self._samples[0]["t"]

    # The save gates, re-exported so the view can show live progress
    # against them without duplicating the numbers.
    MIN_RPM_SPAN = _MIN_RPM_SPAN
    MIN_DURATION_S = _MIN_DURATION_S

    def runs_on_disk(self) -> int:
        if self._car_id is None or self._car_id < 0:
            return 0
        return self.store.count_for(self._car_id)

    # -- frame intake --

    def feed(self, frame) -> None:
        if frame is None or frame.car_id < 0:
            # Demo playback / boot frame: nothing worth recording.
            if self.state == RecorderState.RECORDING:
                self._finish("telemetry lost")
            self.state = RecorderState.IDLE
            self._car_id = None
            return

        if frame.received_time == self._last_received:
            return  # paused or stale link — the frame carries no new data
        self._last_received = frame.received_time

        if frame.car_id != self._car_id:
            if self.state == RecorderState.RECORDING:
                self._finish("car changed")
            self._car_id = frame.car_id
            self._normalizer.reset()
            self.state = RecorderState.ARMED

        throttle = self._normalizer(frame.throttle)

        if self.state != RecorderState.RECORDING:
            self.state = RecorderState.ARMED
            if (
                throttle >= _THROTTLE_ON
                and frame.current_gear >= 1
                and frame.engine_rpm > 0.0
            ):
                self._begin(frame)
            return

        # A run is active.
        if frame.current_gear != self._gear:
            self._finish("gear change")
            return
        if throttle < _THROTTLE_OFF:
            self._finish("throttle lifted")
            return
        rpm = float(frame.engine_rpm)
        if rpm < self._rpm_hi - _RPM_DROP_END:
            self._finish("rev limiter")
            return
        self._rpm_hi = max(self._rpm_hi, rpm)
        self._samples.append(self._sample(frame, throttle))

    # -- internals --

    def _begin(self, frame) -> None:
        self.state = RecorderState.RECORDING
        self._gear = frame.current_gear
        ratios = frame.gear_ratios or []
        self._gear_ratio = (
            float(ratios[self._gear - 1]) if len(ratios) >= self._gear else None
        )
        self._rpm_hi = float(frame.engine_rpm)
        throttle = self._normalizer(frame.throttle)
        self._samples = [self._sample(frame, throttle)]

    @staticmethod
    def _sample(frame, throttle: float) -> dict:
        sample = {
            "t": frame.received_time,
            "rpm": float(frame.engine_rpm),
            "v": float(frame.car_speed),
            "thr": round(throttle, 3),
        }
        wheels = getattr(frame, "wheels", None)
        if wheels is not None:
            sample["ws"] = [
                float(w.ground_speed)
                for w in (
                    wheels.front_left,
                    wheels.front_right,
                    wheels.rear_left,
                    wheels.rear_right,
                )
            ]
        return sample

    def _finish(self, end_reason: str) -> None:
        samples, self._samples = self._samples, []
        self.state = RecorderState.ARMED

        rpm_lo = samples[0]["rpm"] if samples else 0.0
        rpm_hi = self._rpm_hi
        duration = samples[-1]["t"] - samples[0]["t"] if len(samples) > 1 else 0.0

        reject = None
        if len(samples) < _MIN_SAMPLES:
            reject = f"too few samples ({len(samples)})"
        elif duration < _MIN_DURATION_S:
            reject = f"too short ({duration:.1f} s)"
        elif rpm_hi - rpm_lo < _MIN_RPM_SPAN:
            reject = f"rpm span only {int(rpm_hi - rpm_lo)}"

        if reject is not None:
            self.last_result = RunResult(
                False, reject, gear=self._gear,
                rpm_lo=rpm_lo, rpm_hi=rpm_hi, sample_count=len(samples),
            )
            return

        header = {
            "schema": _SCHEMA_VERSION,
            "car_id": self._car_id,
            "gear": self._gear,
            "gear_ratio": self._gear_ratio,
            "rpm_lo": rpm_lo,
            "rpm_hi": rpm_hi,
            "duration_s": round(duration, 3),
            "end_reason": end_reason,
            "created": time.time(),
        }
        path = self.store.save(header, samples)
        self.last_result = RunResult(
            True, end_reason, path=path, gear=self._gear,
            rpm_lo=rpm_lo, rpm_hi=rpm_hi, sample_count=len(samples),
        )
