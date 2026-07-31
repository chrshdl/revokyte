"""AccelRunRecorder: automatic full-throttle run capture.

Synthetic frame sequences drive the state machine end to end: arming,
run detection, the three end triggers (lift, gear change, limiter), the
quality gates, and the on-disk payload.
"""

from dataclasses import dataclass, field

import pytest

from instrument_cluster.core.engine_sim.accel_recorder import (
    AccelRunRecorder,
    AccelRunStore,
    RecorderState,
)


@dataclass
class FakeWheel:
    ground_speed: float = 20.0


@dataclass
class FakeWheels:
    front_left: FakeWheel = field(default_factory=FakeWheel)
    front_right: FakeWheel = field(default_factory=FakeWheel)
    rear_left: FakeWheel = field(default_factory=FakeWheel)
    rear_right: FakeWheel = field(default_factory=FakeWheel)


@dataclass
class FakeFrame:
    received_time: float = 0.0
    car_id: int = 42
    engine_rpm: float = 3000.0
    car_speed: float = 20.0
    throttle: float = 0.0
    current_gear: int = 3
    gear_ratios: list = field(default_factory=lambda: [3.2, 2.1, 1.6, 1.25])
    wheels: FakeWheels = field(default_factory=FakeWheels)


@pytest.fixture
def store(tmp_path):
    return AccelRunStore(tmp_path / "accel_runs")


@pytest.fixture
def recorder(store):
    return AccelRunRecorder(store)


def drive_pull(recorder, t0=0.0, rpm0=3000.0, rpm1=7000.0, seconds=3.0,
               gear=3, hz=60):
    """Feed a clean full-throttle ramp; returns the time after the pull."""
    steps = int(seconds * hz)
    for i in range(steps + 1):
        t = t0 + i / hz
        rpm = rpm0 + (rpm1 - rpm0) * i / steps
        recorder.feed(FakeFrame(
            received_time=t, engine_rpm=rpm, throttle=1.0,
            current_gear=gear, car_speed=15.0 + 20.0 * i / steps,
        ))
    return t0 + seconds


# --- arming ---


def test_idle_without_live_car(recorder):
    recorder.feed(FakeFrame(car_id=-1, throttle=1.0))
    assert recorder.state == RecorderState.IDLE


def test_arms_on_live_car_and_partial_throttle(recorder):
    recorder.feed(FakeFrame(throttle=0.4))
    assert recorder.state == RecorderState.ARMED


def test_stale_frames_are_ignored(recorder):
    frame = FakeFrame(received_time=1.0, throttle=1.0, engine_rpm=4000)
    recorder.feed(frame)
    assert recorder.state == RecorderState.RECORDING
    count = len(recorder._samples)
    recorder.feed(frame)  # same received_time: paused link
    assert len(recorder._samples) == count


# --- accepted runs ---


def test_clean_pull_is_saved(recorder, store):
    t = drive_pull(recorder)
    # lift ends the run
    recorder.feed(FakeFrame(received_time=t + 0.02, throttle=0.1,
                            engine_rpm=7000))
    result = recorder.last_result
    assert result is not None and result.accepted
    assert result.reason == "throttle lifted"
    assert result.gear == 3
    assert store.count_for(42) == 1

    # payload sanity
    import json

    path = result.path
    data = json.loads(path.read_text())
    assert data["header"]["car_id"] == 42
    assert data["header"]["gear"] == 3
    assert data["header"]["gear_ratio"] == 1.6
    assert data["header"]["rpm_hi"] >= 6900
    samples = data["samples"]
    assert len(samples) > 150
    assert {"t", "rpm", "v", "thr", "ws"} <= set(samples[0])


def test_limiter_bounce_ends_and_saves(recorder, store):
    t = drive_pull(recorder)
    # rpm falls hard while the pedal stays down: limiter / ignition cut
    recorder.feed(FakeFrame(received_time=t + 0.02, throttle=1.0,
                            engine_rpm=6500))
    assert recorder.last_result.accepted
    assert recorder.last_result.reason == "rev limiter"
    assert store.count_for(42) == 1


def test_gear_change_ends_run(recorder):
    t = drive_pull(recorder)
    recorder.feed(FakeFrame(received_time=t + 0.02, throttle=1.0,
                            engine_rpm=5200, current_gear=4))
    assert recorder.last_result.accepted
    assert recorder.last_result.reason == "gear change"
    # and the recorder immediately re-arms for the next pull
    assert recorder.state == RecorderState.ARMED


def test_raw_byte_throttle_is_normalized(recorder, store):
    """A proxy feed emitting 0-255 pedals must still trigger capture."""
    hz = 60
    for i in range(int(2.5 * hz)):
        recorder.feed(FakeFrame(
            received_time=i / hz, throttle=255,
            engine_rpm=3000 + 2000 * i / (2.5 * hz),
        ))
    assert recorder.state == RecorderState.RECORDING


# --- rejected runs ---


def test_short_stab_is_discarded(recorder, store):
    drive_pull(recorder, seconds=0.5, rpm1=4000.0)
    recorder.feed(FakeFrame(received_time=0.6, throttle=0.0, engine_rpm=4000))
    result = recorder.last_result
    assert result is not None and not result.accepted
    assert store.count_for(42) == 0


def test_small_rpm_span_is_discarded(recorder, store):
    drive_pull(recorder, seconds=2.0, rpm0=5000.0, rpm1=5800.0)
    recorder.feed(FakeFrame(received_time=2.1, throttle=0.0, engine_rpm=5800))
    result = recorder.last_result
    assert not result.accepted
    assert "span" in result.reason
    assert store.count_for(42) == 0


def test_car_change_mid_run_discards_cleanly(recorder, store):
    drive_pull(recorder, seconds=1.0, rpm1=5000.0)
    recorder.feed(FakeFrame(received_time=1.1, car_id=77, throttle=0.0))
    assert store.count_for(42) == 0
    assert recorder.car_id == 77
    assert recorder.state == RecorderState.ARMED


# --- store ---


def test_store_counts_and_names_runs(store):
    header = {"car_id": 9, "gear": 2, "rpm_lo": 3000.0, "rpm_hi": 7000.0}
    path = store.save(header, [{"t": 0.0}])
    assert path.name == "run_001_g2_3000-7000.json"
    assert store.count_for(9) == 1
    store.save(header, [{"t": 0.0}])
    assert store.count_for(9) == 2
    assert store.count_for(10) == 0
