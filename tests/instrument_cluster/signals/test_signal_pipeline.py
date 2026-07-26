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


def test_unchanged_mode_does_not_reset():
    pipeline = SignalPipeline()
    pipeline.sync_mode()
    assert pipeline._pending_reset is False
