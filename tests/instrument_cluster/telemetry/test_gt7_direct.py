"""Tests for the in-process GT7 reader (telemetry/gt7_direct.py).

The packet stubs mirror the attribute shape of granturismo's ``Packet``
dataclass, so the mapper is exercised without the optional dependency
installed.
"""

import time
from types import SimpleNamespace

from instrument_cluster.telemetry.gt7_direct import Gt7DirectReader, packet_to_frame


def _wheel(temperature=78.5, suspension_height=0.4):
    return SimpleNamespace(
        suspension_height=suspension_height,
        radius=0.33,
        rps=50.0,
        ground_speed=55.0,
        temperature=temperature,
    )


def _flags(paused=False):
    return SimpleNamespace(
        car_on_track=True,
        paused=paused,
        loading_or_processing=False,
        in_gear=True,
        has_turbo=True,
        rev_limiter_alert_active=False,
        hand_brake_active=False,
        lights_active=True,
        lights_high_beams_active=False,
        lights_low_beams_active=True,
        asm_active=False,
        tcs_active=True,
        unused1=False,
        unused2=False,
        unused3=False,
        unused4=False,
    )


def _packet(**overrides):
    packet = SimpleNamespace(
        received_time=123.0,
        car_id=44,
        car_speed=55.5,
        engine_rpm=6400.0,
        current_gear=3,
        throttle=255,
        brake=0,
        gas_level=42.0,
        gas_capacity=100.0,
        lap_count=2,
        laps_in_race=5,
        best_lap_time=97980,
        last_lap_time=99010,
        current_lap_time=45210,
        flags=_flags(),
        rpm_alert=SimpleNamespace(min=7000, max=7500),
        wheels=SimpleNamespace(
            front_left=_wheel(78.5),
            front_right=_wheel(79.5),
            rear_left=_wheel(85.0),
            rear_right=_wheel(86.0),
        ),
        position=SimpleNamespace(x=1.0, y=2.0, z=3.0),
        gear_ratios=[3.2, 2.4, 1.8],
    )
    for key, value in overrides.items():
        setattr(packet, key, value)
    return packet


# --- packet_to_frame ---


def test_maps_core_fields():
    frame = packet_to_frame(_packet())

    assert frame.received_time == 123.0
    assert frame.car_id == 44
    assert frame.car_speed == 55.5
    assert frame.engine_rpm == 6400.0
    assert frame.current_gear == 3
    assert frame.lap_count == 2
    assert frame.laps_in_race == 5
    assert frame.best_lap_time == 97980
    assert frame.last_lap_time == 99010
    assert frame.current_lap_time == 45210
    assert frame.rpm_alert.min == 7000
    assert frame.rpm_alert.max == 7500
    assert frame.wheels.rear_right.temperature == 86.0
    assert frame.position.x == 1.0
    assert frame.position.z == 3.0
    assert frame.gear_ratios == [3.2, 2.4, 1.8]
    assert frame.flags.tcs_active is True
    assert frame.flags.asm_active is False


def test_pedal_bytes_normalize_to_unit_range():
    """GT7 transmits pedals as raw 0-255 bytes; the schema wants 0..1."""
    frame = packet_to_frame(_packet(throttle=255, brake=0))
    assert frame.throttle == 1.0
    assert frame.brake == 0.0

    frame = packet_to_frame(_packet(throttle=51, brake=204))
    assert frame.throttle == 51 / 255
    assert frame.brake == 204 / 255


def test_neutral_gear_none_becomes_minus_one():
    frame = packet_to_frame(_packet(current_gear=None))
    assert frame.current_gear == -1


def test_out_of_range_suspension_is_clamped_not_dropped():
    packet = _packet()
    packet.wheels.front_left.suspension_height = 1.2
    packet.wheels.rear_left.suspension_height = -0.1

    frame = packet_to_frame(packet)

    assert frame.wheels.front_left.suspension_height == 1.0
    assert frame.wheels.rear_left.suspension_height == 0.0


def test_native_fields_stay_unset():
    """GT7 computes neither a delta nor a track name — the signal
    processors' compute paths must stay active."""
    frame = packet_to_frame(_packet())
    assert frame.native_delta_ms is None
    assert frame.track_name is None


# --- Gt7DirectReader ---


class _StubFeed:
    def __init__(self, packets):
        self._packets = list(packets)
        self.started = False
        self.closed = False

    def start(self):
        self.started = True
        return self

    def get_latest(self, timeout=None):
        if self._packets:
            return self._packets.pop(0)
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
    feed = _StubFeed([_packet(car_speed=10.0)])
    reader = Gt7DirectReader("192.168.1.50", feed_factory=lambda ip: feed)

    reader.start()
    try:
        assert feed.started
        assert _wait_for(lambda: reader.latest() is not None)
        assert reader.latest().car_speed == 10.0
    finally:
        reader.stop()

    assert feed.closed


def test_paused_packets_hold_the_last_frame():
    feed = _StubFeed(
        [
            _packet(car_speed=10.0),
            _packet(car_speed=99.0, flags=_flags(paused=True)),
        ]
    )
    reader = Gt7DirectReader("192.168.1.50", feed_factory=lambda ip: feed)

    reader.start()
    try:
        assert _wait_for(lambda: reader.latest() is not None)
        # Both packets have been consumed once the queue is empty; the
        # paused one must not have replaced the live frame.
        assert _wait_for(lambda: not feed._packets)
        time.sleep(0.02)
        assert reader.latest().car_speed == 10.0
    finally:
        reader.stop()


def test_failed_feed_start_leaves_reader_inert():
    def factory(ip):
        raise OSError("port 33740 already bound")

    reader = Gt7DirectReader("192.168.1.50", feed_factory=factory)
    reader.start()

    assert reader.latest() is None
    reader.stop()  # must not raise


def test_stop_before_start_is_safe():
    reader = Gt7DirectReader("192.168.1.50", feed_factory=lambda ip: _StubFeed([]))
    reader.stop()
    assert reader.latest() is None
