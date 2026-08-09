"""Tests for SignalPipeline's session handling on telemetry source
switches: the previous source's frame and computed signals must never
linger on the gauges."""

import json

import pytest

from instrument_cluster.config import ConfigManager
from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus
from instrument_cluster.signals.signal_pipeline import SignalPipeline
from instrument_cluster.telemetry.mode import TelemetryMode
from instrument_cluster.telemetry.models import TelemetryFrame


@pytest.fixture(autouse=True)
def isolated_config(tmp_path):
    ConfigManager.reset()
    ConfigManager.set_path(tmp_path / "config.json")
    (tmp_path / "config.json").write_text(json.dumps({"telemetry_mode": "demo"}))
    yield
    ConfigManager.reset()


def test_mode_switch_resets_bus_to_defaults():
    pipeline = SignalPipeline()
    pipeline.start()
    bus = VehicleBus()
    try:
        pipeline.update(bus, 0.016)
        # Demo telemetry landed and would otherwise stay on the gauges.
        assert bus.frame is not None
        assert bus.frame.car_speed != 0.0
        bus.merge_signals({"stale_demo_key": 123})

        ConfigManager.set_telemetry_mode(TelemetryMode.UDP, persist=False)
        pipeline.sync_mode()
        pipeline.update(bus, 0.016)

        assert "stale_demo_key" not in bus.signals
        # The UDP reader publishes a default frame until real telemetry
        # arrives — every gauge shows its placeholder.
        assert bus.frame == TelemetryFrame()
    finally:
        pipeline.stop()


def test_mode_switch_restarts_the_live_processors():
    pipeline = SignalPipeline()
    old_delta = pipeline._delta_map[TelemetryMode.UDP]
    old_fuel = pipeline._fuel_map[TelemetryMode.UDP]
    old_track = pipeline.track

    ConfigManager.set_telemetry_mode(TelemetryMode.UDP, persist=False)
    pipeline.sync_mode()
    pipeline.stop()

    # A new source is a new session: no lap references, fuel history, or
    # track lock carried over.
    assert pipeline.delta is not old_delta
    assert pipeline.fuel is not old_fuel
    assert pipeline.track is not old_track


def test_direct_host_change_starts_a_fresh_session(monkeypatch):
    pipeline = SignalPipeline()
    pipeline._last_mode = TelemetryMode.DIRECT
    pipeline._last_direct_host = "192.168.1.10"
    cfg = ConfigManager.get_config()
    cfg.telemetry_mode = TelemetryMode.DIRECT.value
    cfg.direct_host = "192.168.1.99"
    refreshed = []
    monkeypatch.setattr(
        pipeline.telemetry, "refresh_direct", lambda: refreshed.append(True)
    )

    pipeline.sync_mode()

    assert refreshed == [True]
    assert pipeline._pending_reset is True


def test_udp_bind_host_change_starts_a_fresh_session(monkeypatch):
    """The agent pairing flow flips udp_host 127.0.0.1 -> 0.0.0.0 while the
    mode stays UDP. Regression: the reader kept its boot-time loopback bind
    until the next reboot, so a freshly paired agent streamed at a cluster
    that never heard it."""
    pipeline = SignalPipeline()
    pipeline._last_mode = TelemetryMode.UDP
    pipeline._last_udp_host = "127.0.0.1"
    cfg = ConfigManager.get_config()
    cfg.telemetry_mode = TelemetryMode.UDP.value
    cfg.udp_host = "0.0.0.0"
    rebound = []
    monkeypatch.setattr(
        pipeline.telemetry, "set_udp_host", lambda host: rebound.append(host)
    )

    pipeline.sync_mode()

    assert rebound == ["0.0.0.0"]
    assert pipeline._pending_reset is True


def test_switch_into_udp_uses_the_current_bind_host(monkeypatch):
    """Mode and bind host can change together (pairing from demo mode):
    the switch must hand the source the current host, not the boot-time one."""
    pipeline = SignalPipeline()  # boots in demo with udp_host 127.0.0.1
    cfg = ConfigManager.get_config()
    cfg.telemetry_mode = TelemetryMode.UDP.value
    cfg.udp_host = "0.0.0.0"

    pipeline.sync_mode()
    pipeline.stop()

    assert pipeline.telemetry._host == "0.0.0.0"
    assert pipeline._last_udp_host == "0.0.0.0"


def test_unchanged_mode_does_not_reset():
    pipeline = SignalPipeline()
    pipeline.sync_mode()
    assert pipeline._pending_reset is False


# --- Link supervision ------------------------------------------------------


def test_link_is_supervised_even_when_no_frame_ever_arrives():
    """A reader that never produces a frame (inert direct reader, feed not
    connected) is exactly the case the driver needs told about.

    Regression: the pipeline returned early on `bus.frame is None`, so the
    dashboard sat blank and silent instead of reporting the dead link.
    """
    pipeline = SignalPipeline()
    pipeline.telemetry = _NullTelemetry()
    pipeline.start()
    bus = VehicleBus()
    try:
        for _ in range(120):  # 2 s, past the 1 s threshold
            pipeline.update(bus, 0.016)
        assert bus.frame is None
        assert bus.signals["telemetry_stale"] is True
    finally:
        pipeline._active = False


def test_live_demo_telemetry_never_reports_a_stale_link():
    pipeline = SignalPipeline()
    pipeline.start()
    bus = VehicleBus()
    try:
        for _ in range(120):
            pipeline.update(bus, 0.016)
        assert bus.signals["telemetry_stale"] is False
    finally:
        pipeline.stop()


def test_a_frozen_reader_goes_stale():
    """UdpJsonlReader hands back its last frame forever; after the threshold
    that must stop reading as live data."""
    pipeline = SignalPipeline()
    pipeline.telemetry = _FrozenTelemetry()
    pipeline.start()
    bus = VehicleBus()
    try:
        pipeline.update(bus, 0.016)
        assert bus.signals["telemetry_stale"] is False

        for _ in range(120):
            pipeline.update(bus, 0.016)
        assert bus.signals["telemetry_stale"] is True
    finally:
        pipeline._active = False


class _NullTelemetry:
    def start(self):
        pass

    def stop(self):
        pass

    def latest(self):
        return None


class _FrozenTelemetry:
    """Always returns the same frame object, as a reader does when the feed
    has gone quiet."""

    def __init__(self):
        self._frame = TelemetryFrame(received_time=1234.5)

    def start(self):
        pass

    def stop(self):
        pass

    def latest(self):
        return self._frame
