"""Tests for TelemetrySource's direct-mode handling (telemetry/source.py)."""

from instrument_cluster.telemetry.mode import TelemetryMode
from instrument_cluster.telemetry.models import TelemetryFrame
from instrument_cluster.telemetry.source import TelemetrySource


class _StubReader:
    def __init__(self):
        self.started = 0
        self.stopped = 0
        self._frame = TelemetryFrame(car_speed=42.0)

    def start(self):
        self.started += 1

    def latest(self):
        return self._frame

    def stop(self):
        self.stopped += 1


class _CountingFactory:
    def __init__(self):
        self.readers = []

    def __call__(self):
        reader = _StubReader()
        self.readers.append(reader)
        return reader


def test_direct_mode_uses_the_factory_reader():
    factory = _CountingFactory()
    source = TelemetrySource(
        mode=TelemetryMode.DIRECT, direct_reader_factory=factory
    )

    assert len(factory.readers) == 1
    assert source.reader is factory.readers[0]
    assert source.latest().car_speed == 42.0


def test_direct_factory_failure_falls_back_to_inert_reader():
    def broken():
        raise RuntimeError("no feed configured")

    source = TelemetrySource(
        mode=TelemetryMode.DIRECT, direct_reader_factory=broken
    )

    # Inert, not demo: no synthetic motion pretending to be live data.
    source.start()
    assert source.latest() is None
    source.stop()


def test_no_factory_at_all_falls_back_to_inert_reader():
    source = TelemetrySource(mode=TelemetryMode.DIRECT)
    assert source.latest() is None


def test_switching_away_discards_the_direct_reader():
    factory = _CountingFactory()
    source = TelemetrySource(
        mode=TelemetryMode.DIRECT, direct_reader_factory=factory
    )

    source.switch_mode(TelemetryMode.DEMO)
    source.switch_mode(TelemetryMode.DIRECT)

    # A stopped direct reader is not restartable — coming back must build
    # a fresh one.
    assert len(factory.readers) == 2
    assert factory.readers[0].stopped == 1
    assert factory.readers[1].started == 1


def test_refresh_direct_rebuilds_the_reader_in_place():
    factory = _CountingFactory()
    source = TelemetrySource(
        mode=TelemetryMode.DIRECT, direct_reader_factory=factory
    )
    source.start()

    source.refresh_direct()

    assert len(factory.readers) == 2
    assert factory.readers[0].stopped == 1
    assert factory.readers[1].started == 1
    assert source.reader is factory.readers[1]


def test_refresh_direct_is_a_noop_in_other_modes():
    factory = _CountingFactory()
    source = TelemetrySource(
        mode=TelemetryMode.DEMO, direct_reader_factory=factory
    )

    source.refresh_direct()

    assert factory.readers == []
    assert source.mode == TelemetryMode.DEMO
