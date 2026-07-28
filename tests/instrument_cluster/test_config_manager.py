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


# --- persist(): the single background writer ---
#
# NOTE: never monkeypatch threading.Thread in the config module — the
# "config-writer" thread is created once for the process lifetime, so a
# patched class would be baked in for every later test. Patch
# _write_config_dict instead and use ConfigManager.flush() for determinism.


@pytest.fixture
def write_calls(monkeypatch):
    """Records the writer's disk I/O instead of touching the filesystem."""
    calls = []
    monkeypatch.setattr(
        "instrument_cluster.config._write_config_dict",
        lambda config_dict, path: calls.append(config_dict),
    )
    return calls


@pytest.fixture
def gated_write(monkeypatch):
    """Replaces the writer's disk I/O with a gate the test controls: records
    each config dict and the writing thread at entry, sets `entered`, then
    blocks until `release`. Released on teardown (and the wait is bounded)
    so a failing test can't wedge the writer — and with it the flush inside
    ConfigManager.reset()."""
    calls = []
    entered = threading.Event()
    release = threading.Event()

    def _gated(config_dict, path):
        calls.append((config_dict, threading.current_thread()))
        entered.set()
        release.wait(timeout=5)

    monkeypatch.setattr("instrument_cluster.config._write_config_dict", _gated)
    yield calls, entered, release
    release.set()


def test_persist_does_not_block_the_caller(config_path, gated_write):
    """The disk write must happen on the background writer thread —
    persist() returns even while the write itself is stuck at the gate."""
    calls, entered, release = gated_write
    cfg = _load(config_path, {"brightness": 50})
    cfg.brightness = 77

    ConfigManager.persist()  # a synchronous write would deadlock here

    assert entered.wait(timeout=2)
    release.set()
    assert ConfigManager.flush(timeout=2)

    assert len(calls) == 1
    written, thread = calls[0]
    assert written["brightness"] == 77
    assert thread is not threading.current_thread()
    assert thread.name == "config-writer"


def test_persist_writes_current_config_to_disk(config_path):
    cfg = _load(config_path, {"brightness": 50})
    cfg.brightness = 77

    ConfigManager.persist()
    assert ConfigManager.flush(timeout=2)

    assert json.loads(config_path.read_text())["brightness"] == 77


def test_redundant_persists_coalesce_into_the_latest_state(config_path, gated_write):
    """persist() calls issued while a write is in flight collapse into a
    single write of the newest snapshot — the middle value never lands."""
    calls, entered, release = gated_write
    cfg = _load(config_path, {"brightness": 50})

    cfg.brightness = 60
    ConfigManager.persist()
    assert entered.wait(timeout=2)  # first write is now in flight, gated

    cfg.brightness = 70
    ConfigManager.persist()
    cfg.brightness = 80
    ConfigManager.persist()  # overwrites the pending 70 snapshot

    release.set()
    assert ConfigManager.flush(timeout=2)

    assert [written["brightness"] for written, _ in calls] == [60, 80]


def test_persist_of_unchanged_config_skips_the_write(config_path, write_calls):
    _load(config_path, {"brightness": 50})

    ConfigManager.persist()
    assert ConfigManager.flush(timeout=2)

    assert write_calls == []


def test_flush_with_nothing_pending_returns_immediately():
    assert ConfigManager.flush(timeout=0.1)


def test_flush_times_out_while_a_write_is_stuck(config_path, gated_write):
    calls, entered, release = gated_write
    cfg = _load(config_path, {"brightness": 50})
    cfg.brightness = 77
    ConfigManager.persist()
    assert entered.wait(timeout=2)

    assert ConfigManager.flush(timeout=0.05) is False

    release.set()
    assert ConfigManager.flush(timeout=2) is True


# --- Direct telemetry mode ---


def test_direct_mode_with_host_is_kept(config_path):
    cfg = _load(
        config_path,
        {"telemetry_mode": "direct", "direct_host": "192.168.1.50"},
    )
    assert cfg.telemetry_mode == TelemetryMode.DIRECT.value
    assert cfg.direct_host == "192.168.1.50"


def test_direct_mode_without_host_demotes_to_demo(config_path):
    cfg = _load(config_path, {"telemetry_mode": "direct"})
    assert cfg.telemetry_mode == TelemetryMode.DEMO.value


def test_set_direct_host_strips_and_persists(config_path):
    _load(config_path, {})
    ConfigManager.set_direct_host("  192.168.1.7  ")
    assert ConfigManager.flush(timeout=2)

    assert ConfigManager.get_config().direct_host == "192.168.1.7"
    assert json.loads(config_path.read_text())["direct_host"] == "192.168.1.7"


def test_diff_reference_mode_labels_are_display_ready():
    """One source for Setup's dropdown and the delta gauge header."""
    from instrument_cluster.telemetry.mode import DiffReferenceMode

    assert DiffReferenceMode.FASTEST.label == "Fastest"
    assert DiffReferenceMode.PREVIOUS.label == "Previous"

    for mode in DiffReferenceMode:
        # The label must stay recognisable as the persisted config value —
        # that link is what keeps the two screens naming one setting alike.
        assert mode.label.lower().replace(" ", "_") == mode.value
        assert mode.label[0].isupper()


def test_installing_a_feed_records_its_version(tmp_path):
    """Which build is on the device, not just which feed — that is what lets
    a later image notice the install is stale."""
    from instrument_cluster.config import ConfigManager

    ConfigManager.reset()
    ConfigManager.set_path(tmp_path / "config.json")

    ConfigManager.set_telemetry_feed("granturismo", "v0.3.16", persist=False)
    cfg = ConfigManager.get_config()

    assert cfg.telemetry_feed == "granturismo"
    assert cfg.telemetry_feed_version == "v0.3.16"


def test_feed_version_defaults_to_unknown():
    """Configs written before the field existed still parse."""
    from instrument_cluster.config import Config

    assert Config().telemetry_feed_version == ""
