"""Tests for the in-process ACC reader (telemetry/acc_direct.py).

The frame stubs are local dataclasses mirroring ``acc.model.Frame`` — the
mapper is ``dataclasses.asdict`` + pydantic validation, so real dataclasses
exercise it without the optional dependency installed.
"""

import time
from dataclasses import dataclass, field

from instrument_cluster.telemetry.acc_direct import AccDirectReader, acc_frame_to_frame


@dataclass
class _Vector:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class _Flags:
    car_on_track: bool = False
    paused: bool = False
    loading_or_processing: bool = False


@dataclass
class _Frame:
    received_time: float = 123.0
    car_speed: float = 51.4
    current_gear: int = 4
    lap_count: int | None = 7
    current_lap_time: int | None = 45210
    last_lap_time: int | None = 99010
    best_lap_time: int | None = 97980
    native_delta_ms: int | None = -312
    track_name: str | None = "Monza"
    position: _Vector = field(default_factory=lambda: _Vector(x=1.0, z=3.0))
    flags: _Flags = field(default_factory=lambda: _Flags(car_on_track=True))


# --- acc_frame_to_frame ---


def test_maps_core_fields():
    frame = acc_frame_to_frame(_Frame())

    assert frame.received_time == 123.0
    assert frame.car_speed == 51.4
    assert frame.current_gear == 4
    assert frame.lap_count == 7
    assert frame.current_lap_time == 45210
    assert frame.last_lap_time == 99010
    assert frame.best_lap_time == 97980
    assert frame.position.x == 1.0
    assert frame.position.z == 3.0
    assert frame.flags.car_on_track is True


def test_native_fields_come_through_set():
    """ACC provides its own delta and track name — DeltaSignal/TrackSignal
    must switch to their republish paths (the inverse of GT7)."""
    frame = acc_frame_to_frame(_Frame())
    assert frame.native_delta_ms == -312
    assert frame.track_name == "Monza"


def test_channels_acc_lacks_take_schema_defaults():
    frame = acc_frame_to_frame(_Frame())
    assert frame.engine_rpm == 0.0
    assert frame.car_id == -1
    assert frame.wheels is None
    assert frame.gear_ratios is None


# --- AccDirectReader ---


class _StubFeed:
    def __init__(self, frames):
        self._frames = list(frames)
        self.started = False
        self.closed = False

    def start(self):
        self.started = True
        return self

    def get_latest(self, timeout=None):
        if self._frames:
            return self._frames.pop(0)
        time.sleep(0.002)
        return None

    def close(self):
        self.closed = True


def _wait_for(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return False


def test_reader_publishes_mapped_frames():
    feed = _StubFeed([_Frame(car_speed=10.0)])
    reader = AccDirectReader("192.168.1.60", feed_factory=lambda ip: feed)

    reader.start()
    try:
        assert feed.started
        assert _wait_for(lambda: reader.latest() is not None)
        assert reader.latest().car_speed == 10.0
    finally:
        reader.stop()

    assert feed.closed


def test_paused_frames_hold_the_last_frame():
    feed = _StubFeed(
        [
            _Frame(car_speed=10.0),
            _Frame(car_speed=99.0, flags=_Flags(paused=True)),
        ]
    )
    reader = AccDirectReader("192.168.1.60", feed_factory=lambda ip: feed)

    reader.start()
    try:
        assert _wait_for(lambda: reader.latest() is not None)
        assert _wait_for(lambda: not feed._frames)
        time.sleep(0.02)
        assert reader.latest().car_speed == 10.0
    finally:
        reader.stop()


def test_failed_feed_start_leaves_reader_inert():
    def factory(ip):
        raise OSError("no route to host")

    reader = AccDirectReader("192.168.1.60", feed_factory=factory)
    reader.start()

    assert reader.latest() is None
    reader.stop()  # must not raise


def test_stop_before_start_is_safe():
    reader = AccDirectReader("192.168.1.60", feed_factory=lambda ip: _StubFeed([]))
    reader.stop()
    assert reader.latest() is None
