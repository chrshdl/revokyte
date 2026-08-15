"""Tests for the factory-reset data erase (core/system/factory_reset.py)."""

from pathlib import Path

from instrument_cluster.core.system import factory_reset


def _populate(data_root: Path, config_path: Path) -> None:
    (data_root / "config").mkdir(parents=True)
    config_path.write_text('{"direct_host": "192.168.1.50"}')

    (data_root / "opt" / "telemetry" / "active").mkdir(parents=True)
    (data_root / "opt" / "telemetry" / "active" / "proxy.py").write_text("x")
    (data_root / "etc").mkdir(parents=True)
    (data_root / "etc" / "instrument-cluster-proxy").write_text("HOST=192.168.1.99")
    (data_root / "plugins" / "myplugin").mkdir(parents=True)
    (data_root / "plugins" / "myplugin" / "myplugin.py").write_text("y")

    wifi = data_root / "etc" / "wpa_supplicant"
    wifi.mkdir(parents=True)
    (wifi / "wpa_supplicant-wlan0.conf").write_text(
        'ctrl_interface=/run/wpa_supplicant\nupdate_config=1\n'
        'network={\n\tssid="HomeNet"\n\tpsk="secret-password"\n}\n'
    )


def test_removes_all_personal_data(tmp_path):
    data_root = tmp_path / "data"
    config_path = data_root / "config" / "instrument-cluster.json"
    wifi_conf = data_root / "etc" / "wpa_supplicant" / "wpa_supplicant-wlan0.conf"
    _populate(data_root, config_path)

    factory_reset.perform_factory_reset(
        config_path=config_path,
        data_root=data_root,
        wifi_conf_path=wifi_conf,
        reboot=False,
    )

    # Personal data gone.
    assert not config_path.exists()
    assert not (data_root / "opt" / "telemetry").exists()
    assert not (data_root / "etc" / "instrument-cluster-proxy").exists()
    assert not (data_root / "plugins").exists()


def test_wifi_config_reset_to_header_only_seed(tmp_path):
    data_root = tmp_path / "data"
    config_path = data_root / "config" / "instrument-cluster.json"
    wifi_conf = data_root / "etc" / "wpa_supplicant" / "wpa_supplicant-wlan0.conf"
    _populate(data_root, config_path)

    factory_reset.perform_factory_reset(
        config_path=config_path,
        data_root=data_root,
        wifi_conf_path=wifi_conf,
        reboot=False,
    )

    # File still exists, but the network block (and the plaintext password)
    # is gone — reduced to exactly the pristine seed.
    assert wifi_conf.exists()
    contents = wifi_conf.read_text()
    assert contents == factory_reset._WPA_SEED
    assert "secret-password" not in contents
    assert "HomeNet" not in contents
    # 0600 so the credential file the user re-creates is not world-readable.
    assert (wifi_conf.stat().st_mode & 0o777) == 0o600


def test_reboot_callback_invoked_when_requested(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    config_path = data_root / "config" / "instrument-cluster.json"
    wifi_conf = data_root / "etc" / "wpa_supplicant" / "wpa_supplicant-wlan0.conf"
    _populate(data_root, config_path)

    called = []
    monkeypatch.setattr(factory_reset, "_reboot", lambda: called.append(True))

    factory_reset.perform_factory_reset(
        config_path=config_path,
        data_root=data_root,
        wifi_conf_path=wifi_conf,
        reboot=True,
    )
    assert called == [True]


def test_no_reboot_when_disabled(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    config_path = data_root / "config" / "instrument-cluster.json"
    wifi_conf = data_root / "etc" / "wpa_supplicant" / "wpa_supplicant-wlan0.conf"
    _populate(data_root, config_path)

    called = []
    monkeypatch.setattr(factory_reset, "_reboot", lambda: called.append(True))

    factory_reset.perform_factory_reset(
        config_path=config_path,
        data_root=data_root,
        wifi_conf_path=wifi_conf,
        reboot=False,
    )
    assert called == []


def test_missing_targets_are_tolerated(tmp_path, monkeypatch):
    # Nothing populated: every target is absent. Must not raise.
    data_root = tmp_path / "data"
    config_path = data_root / "config" / "instrument-cluster.json"
    wifi_conf = data_root / "etc" / "wpa_supplicant" / "wpa_supplicant-wlan0.conf"

    monkeypatch.setattr(factory_reset, "_reboot", lambda: None)
    factory_reset.perform_factory_reset(
        config_path=config_path,
        data_root=data_root,
        wifi_conf_path=wifi_conf,
        reboot=False,
    )
    # The seed is written even when the file did not exist before.
    assert wifi_conf.read_text() == factory_reset._WPA_SEED


def test_reboot_reset_survives_the_shutdown_persist(tmp_path, monkeypatch):
    """The on-device resurrection bug (found 2026-08-15): reset deletes the
    config file, systemctl reboot delivers SIGTERM, and the state
    teardown's persist-on-exit (SetupState) wrote the still-live in-memory
    config straight back — brightness, entered IPs and all. The writer's
    no-op skip can't catch it: _last_written only knows what this process
    wrote, which after a settings-free session is nothing."""
    from instrument_cluster.config import ConfigManager
    from instrument_cluster.core.system import factory_reset

    config_path = tmp_path / "config.json"
    config_path.write_text('{"brightness": 90, "direct_host": "10.0.0.7"}')
    ConfigManager.set_path(config_path)
    try:
        ConfigManager.get_config()  # parse from disk: 90 is live in memory
        monkeypatch.setattr(factory_reset, "_reboot", lambda: None)

        factory_reset.perform_factory_reset(
            config_path=config_path,
            data_root=tmp_path / "data",
            wifi_conf_path=tmp_path / "data" / "wpa.conf",
            reboot=True,
        )
        assert not config_path.exists()

        # What the shutdown path does on the way down:
        ConfigManager.persist()
        assert ConfigManager.flush(timeout=2.0)
        assert not config_path.exists(), "erased config resurrected"
    finally:
        ConfigManager.reset()


def test_dev_reset_keeps_persistence_alive(tmp_path):
    """Off the appliance the process lives on — later settings changes may
    legitimately recreate the config file."""
    from instrument_cluster.config import ConfigManager
    from instrument_cluster.core.system import factory_reset

    config_path = tmp_path / "config.json"
    config_path.write_text('{"brightness": 90}')
    ConfigManager.set_path(config_path)
    try:
        ConfigManager.get_config()
        factory_reset.perform_factory_reset(
            config_path=config_path,
            data_root=tmp_path / "data",
            wifi_conf_path=tmp_path / "data" / "wpa.conf",
            reboot=False,
        )
        assert not config_path.exists()

        ConfigManager.set_brightness_percent(60)
        assert ConfigManager.flush(timeout=2.0)
        assert config_path.exists()
    finally:
        ConfigManager.reset()
