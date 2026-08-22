"""Tests for the in-process FH6 reader (telemetry/fh6_direct.py).

The packet stubs mirror the attribute shape of forza-horizon-6's ``Packet``
dataclass, so the mapper is exercised without the optional dependency
installed.
"""

import time
from types import SimpleNamespace

from instrument_cluster.telemetry.fh6_direct import Fh6DirectReader, packet_to_frame


def _packet(**overrides):
    packet = SimpleNamespace(
        received_time=123.0,
        car_ordinal=42,
        speed=55.5,
        current_engine_rpm=6400.0,
        engine_max_rpm=7000.0,
        gear=2,  # -> map_gear(2) == 1
        accel=255,
        brake=0,
        fuel=0.75,
        lap_number=3,
        best_lap=90.0,
        last_lap=95.0,
        current_lap=45.0,
        is_race_on=True,
        position=SimpleNamespace(x=1.0, y=2.0, z=3.0),
    )
    for key, value in overrides.items():
        setattr(packet, key, value)
    return packet


# --- packet_to_frame ---


def test_maps_core_fields():
    frame = packet_to_frame(_packet())

    assert frame.received_time == 123.0
    assert frame.car_id == 42
    assert frame.car_speed == 55.5
    assert frame.engine_rpm == 6400.0
    assert frame.current_gear == 1
    assert frame.throttle == 1.0
    assert frame.brake == 0.0
    assert frame.gas_level == 0.75
    assert frame.gas_capacity == 1.0
    assert frame.lap_count == 3
    assert frame.best_lap_time == 90000
    assert frame.last_lap_time == 95000
    assert frame.current_lap_time == 45000
    assert frame.position.x == 1.0
    assert frame.position.z == 3.0
    assert frame.flags.car_on_track is True
    assert frame.flags.paused is False
    assert frame.rpm_alert.max == 7000.0
    assert frame.rpm_alert.min == 7000.0 * 0.95


def test_gear_mapping_matches_the_unconfirmed_placeholder():
    # Mirrors fh6.model.frame.map_gear(): 0=reverse, 1=neutral, 2+ -> n-1.
    assert packet_to_frame(_packet(gear=0)).current_gear == 0
    assert packet_to_frame(_packet(gear=1)).current_gear == -1
    assert packet_to_frame(_packet(gear=3)).current_gear == 2


def test_lap_time_zero_means_not_applicable():
    frame = packet_to_frame(_packet(best_lap=0.0, last_lap=0.0, current_lap=0.0))
    assert frame.best_lap_time is None
    assert frame.last_lap_time is None
    assert frame.current_lap_time is None


def test_flags_derive_from_is_race_on():
    frame = packet_to_frame(_packet(is_race_on=False))
    assert frame.flags.car_on_track is False
    assert frame.flags.paused is True


def test_rpm_alert_absent_when_max_rpm_zero():
    frame = packet_to_frame(_packet(engine_max_rpm=0.0))
    assert frame.rpm_alert is None


def test_wheels_and_gear_ratios_stay_unset():
    """FH6 has no data for either; explicit None would fail validation."""
    frame = packet_to_frame(_packet())
    assert frame.wheels is None
    assert frame.gear_ratios is None


# --- Fh6DirectReader ---


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
    feed = _StubFeed([_packet(speed=10.0)])
    reader = Fh6DirectReader("unused", feed_factory=lambda: feed)

    reader.start()
    try:
        assert feed.started
        assert _wait_for(lambda: reader.latest() is not None)
        assert reader.latest().car_speed == 10.0
    finally:
        reader.stop()

    assert feed.closed


def test_failed_feed_start_leaves_reader_inert():
    def factory():
        raise OSError("port 7300 already bound")

    reader = Fh6DirectReader("unused", feed_factory=factory)
    reader.start()

    assert reader.latest() is None
    reader.stop()  # must not raise


def test_stop_before_start_is_safe():
    reader = Fh6DirectReader("unused", feed_factory=lambda: _StubFeed([]))
    reader.stop()
    assert reader.latest() is None
