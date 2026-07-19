import json
import threading

import pytest

from instrument_cluster.config import Config, ConfigManager
from instrument_cluster.telemetry.mode import DiffReferenceMode, TelemetryMode


@pytest.fixture(autouse=True)
def reset_manager():
    """Ensure ConfigManager doesn't bleed state between tests."""
    ConfigManager.reset()
    yield
    ConfigManager.reset()


@pytest.fixture
def config_path(tmp_path):
    return tmp_path / "config.json"


def _load(config_path, data: dict) -> Config:
    config_path.write_text(json.dumps(data))
    ConfigManager.set_path(config_path)
    return ConfigManager.get_config()


# --- Legacy migration ---


def test_migrates_previous_lap_double_space(config_path):
    cfg = _load(config_path, {"diff_reference_mode": "previous"})
    assert cfg.diff_reference_mode == DiffReferenceMode.PREVIOUS.value


def test_migrates_fastest_lap_double_space(config_path):
    cfg = _load(config_path, {"diff_reference_mode": "fastest"})
    assert cfg.diff_reference_mode == DiffReferenceMode.FASTEST.value


def test_valid_diff_mode_not_changed(config_path):
    cfg = _load(config_path, {"diff_reference_mode": "previous"})
    assert cfg.diff_reference_mode == "previous"


# --- Brightness clamping ---


def test_brightness_clamped_above_100(config_path):
    cfg = _load(config_path, {"brightness": 200})
    assert cfg.brightness == 100


def test_brightness_clamped_below_0(config_path):
    cfg = _load(config_path, {"brightness": -5})
    assert cfg.brightness == 0


def test_brightness_at_boundary_100_kept(config_path):
    cfg = _load(config_path, {"brightness": 100})
    assert cfg.brightness == 100


def test_brightness_at_boundary_0_kept(config_path):
    cfg = _load(config_path, {"brightness": 0})
    assert cfg.brightness == 0


# --- Enum validation ---


def test_invalid_telemetry_mode_defaults_to_demo(config_path):
    cfg = _load(config_path, {"telemetry_mode": "satellite"})
    assert cfg.telemetry_mode == TelemetryMode.DEMO.value


def test_valid_telemetry_mode_kept(config_path):
    cfg = _load(config_path, {"telemetry_mode": "udp"})
    assert cfg.telemetry_mode == TelemetryMode.UDP.value


def test_invalid_diff_mode_defaults_to_fastest(config_path):
    cfg = _load(config_path, {"diff_reference_mode": "bogus_value"})
    assert cfg.diff_reference_mode == DiffReferenceMode.FASTEST.value


# --- Corrupt / missing file ---


def test_corrupt_json_returns_defaults(config_path):
    config_path.write_text("{not valid json}")
    ConfigManager.set_path(config_path)
    cfg = ConfigManager.get_config()
    assert cfg.telemetry_mode == TelemetryMode.DEMO.value
    assert cfg.brightness == 50


def test_missing_file_returns_defaults(config_path):
    ConfigManager.set_path(config_path)
    cfg = ConfigManager.get_config()
    assert cfg.telemetry_mode == TelemetryMode.DEMO.value


# --- Unknown keys don't crash ---


def test_unknown_keys_in_config_are_ignored(config_path):
    cfg = _load(config_path, {"brightness": 80, "undiscovered_setting": "yes"})
    assert cfg.brightness == 80


# --- persist() writes off the main thread ---


@pytest.fixture
def captured_thread(monkeypatch):
    """Wraps threading.Thread so the test can join() the exact thread
    persist() spawns, instead of guessing at timing or sweeping every
    thread in the process."""
    spawned = []
    real_thread = threading.Thread

    def _capture(*args, **kwargs):
        t = real_thread(*args, **kwargs)
        spawned.append(t)
        return t

    monkeypatch.setattr("instrument_cluster.config.threading.Thread", _capture)
    return spawned


def test_persist_does_not_block_the_caller(config_path, captured_thread):
    """The actual disk write must happen on a background thread — persist()
    itself should return immediately regardless of write speed."""
    cfg = _load(config_path, {"brightness": 50})
    cfg.brightness = 77

    ConfigManager.persist()

    assert len(captured_thread) == 1
    assert captured_thread[0] is not threading.current_thread()
    captured_thread[0].join(timeout=2)


def test_persist_writes_current_config_to_disk(config_path, captured_thread):
    cfg = _load(config_path, {"brightness": 50})
    cfg.brightness = 77

    ConfigManager.persist()
    captured_thread[0].join(timeout=2)

    assert json.loads(config_path.read_text())["brightness"] == 77
