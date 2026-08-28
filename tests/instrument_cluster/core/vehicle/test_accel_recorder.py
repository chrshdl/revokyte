"""Full-throttle run capture: what gets kept, and what quietly must not.

The recorder is the only source of measured engine curves, so a run it
silently drops is a lap of driving thrown away, and a run it keeps that
should have been dropped becomes a wrong number in ecu.py's class table.
"""

from instrument_cluster.core.vehicle.accel_recorder import (
    AccelRunRecorder,
    AccelRunStore,
    RecorderState,
)
from instrument_cluster.telemetry.models import Flags, TelemetryFrame


def _pull(
    car_id: int = 1461,
    gear: int = 3,
    throttle: float = 1.0,
    rpm_lo: float = 3000.0,
    rpm_hi: float = 8000.0,
    seconds: float = 4.0,
    t0: float = 0.0,
) -> list[TelemetryFrame]:
    """A clean 60 Hz pull: rpm and speed rising together at full throttle."""
    count = max(2, int(seconds * 60))
    frames = []
    for i in range(count):
        share = i / (count - 1)
        rpm = rpm_lo + (rpm_hi - rpm_lo) * share
        frames.append(
            TelemetryFrame(
                car_id=car_id,
                received_time=t0 + i / 60.0,
                engine_rpm=rpm,
                car_speed=rpm * 0.0125,
                current_gear=gear,
                throttle=throttle,
                gear_ratios=[3.321, 1.902, 1.308, 1.0, 0.759],
                flags=Flags(car_on_track=True, in_gear=True),
            )
        )
    return frames


def _recorder(tmp_path) -> AccelRunRecorder:
    return AccelRunRecorder(AccelRunStore(tmp_path))


def test_a_clean_pull_is_kept(tmp_path):
    recorder = _recorder(tmp_path)
    for frame in _pull():
        recorder.feed(frame)
    recorder.feed(None)  # end of stream, as record_runs.py flushes it

    result = recorder.last_result
    assert result.accepted, result.reason
    assert result.gear == 3
    assert result.path.exists()
    assert recorder.store.count_for(1461) == 1


def test_a_lift_ends_the_run(tmp_path):
    """The pedal coming up is the end of the pull, not a gap in it: what
    follows is coasting, and averaging it in flattens the measured curve."""
    recorder = _recorder(tmp_path)
    for frame in _pull():
        recorder.feed(frame)
    lifted = _pull(t0=10.0)[0].model_copy(update={"throttle": 0.5})
    recorder.feed(lifted)

    assert recorder.last_result.accepted
    assert recorder.state == RecorderState.ARMED


def test_a_short_pull_is_dropped(tmp_path):
    """Below the gates the shape is noise. Nothing is written, and the
    reason says which gate — a dropped run must be diagnosable."""
    recorder = _recorder(tmp_path)
    for frame in _pull(rpm_lo=6000.0, rpm_hi=6800.0, seconds=1.0):
        recorder.feed(frame)
    recorder.feed(None)

    assert not recorder.last_result.accepted
    assert recorder.store.count_for(1461) == 0


def test_a_raw_byte_throttle_still_counts_as_full(tmp_path):
    """PROTOCOL.md §3.6 says throttle is 0..1, but the GT7 feed proxy emits
    raw 0-255 (documented in its known-deviations table). Without the
    normalizer the gate reads 255 as full and 200 as full too, so a
    part-throttle pull would be measured as a flat-out one."""
    recorder = _recorder(tmp_path)
    for frame in _pull(throttle=255.0):
        recorder.feed(frame)
    recorder.feed(None)
    assert recorder.last_result.accepted

    partial = _recorder(tmp_path)
    for frame in _pull(car_id=24, throttle=200.0):  # ~78% pedal
        partial.feed(frame)
    partial.feed(None)
    assert partial.store.count_for(24) == 0


def test_an_upshift_splits_the_pull(tmp_path):
    """One run is one gear: wheel force per gear is what the fit reads, so
    two gears in one file would blend two different force curves."""
    recorder = _recorder(tmp_path)
    for frame in _pull(gear=2):
        recorder.feed(frame)
    for frame in _pull(gear=3, t0=5.0):
        recorder.feed(frame)
    recorder.feed(None)

    assert recorder.store.count_for(1461) == 2
