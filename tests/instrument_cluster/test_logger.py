"""The debug file log — the only way a log leaves a release image (no SSH)."""

import importlib
import logging

from instrument_cluster import logger as logger_module


def _reset(monkeypatch, tmp_path, **env):
    importlib.reload(logger_module)
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return root


def test_no_file_log_without_marker_or_env(monkeypatch, tmp_path):
    root = _reset(monkeypatch, tmp_path)
    monkeypatch.delenv(logger_module.DEBUG_LOG_ENV, raising=False)
    monkeypatch.setattr(logger_module, "DEBUG_MARKER", tmp_path / "absent")
    assert logger_module.install_debug_file_log() is None
    assert not any(
        isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers
    )


def test_env_override_writes_records_to_the_file(monkeypatch, tmp_path):
    target = tmp_path / "boot" / "instrument-cluster.log"
    _reset(monkeypatch, tmp_path, **{logger_module.DEBUG_LOG_ENV: str(target)})

    assert logger_module.install_debug_file_log() == target
    logger_module.Logger("wifi_manager").get().warning("no lease on wlan0")

    assert "no lease on wlan0" in target.read_text()


def test_marker_file_enables_the_boot_partition_log(monkeypatch, tmp_path):
    marker = tmp_path / "instrument-cluster-debug"
    marker.touch()
    target = tmp_path / "instrument-cluster.log"
    _reset(monkeypatch, tmp_path)
    monkeypatch.delenv(logger_module.DEBUG_LOG_ENV, raising=False)
    monkeypatch.setattr(logger_module, "DEBUG_MARKER", marker)
    monkeypatch.setattr(logger_module, "DEBUG_LOG_PATH", target)

    assert logger_module.install_debug_file_log() == target
    logging.getLogger("anything").error("boom")
    assert "boom" in target.read_text()


def test_unwritable_path_is_not_fatal(monkeypatch, tmp_path):
    _reset(
        monkeypatch,
        tmp_path,
        **{logger_module.DEBUG_LOG_ENV: "/nonexistent-root/nope.log"},
    )
    assert logger_module.install_debug_file_log() is None  # logged, not raised


def test_installs_only_once(monkeypatch, tmp_path):
    target = tmp_path / "once.log"
    _reset(monkeypatch, tmp_path, **{logger_module.DEBUG_LOG_ENV: str(target)})
    assert logger_module.install_debug_file_log() == target
    assert logger_module.install_debug_file_log() is None


def test_debug_log_does_not_silence_the_console(monkeypatch, tmp_path):
    """Enabling the file log must ADD a sink, never replace the console one.

    install_debug_file_log() attaches to the *root* logger. Logger.__init__
    used to guard its StreamHandler with hasHandlers(), which walks ancestors
    — so the root file handler made every named logger skip its console
    handler, and turning the support marker on turned journal logging off.
    """
    target = tmp_path / "instrument-cluster.log"
    _reset(monkeypatch, tmp_path, **{logger_module.DEBUG_LOG_ENV: str(target)})

    assert logger_module.install_debug_file_log() == target
    root = logging.getLogger()
    assert any(
        isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers
    )

    # A logger created *after* the file handler exists still gets a console one.
    log = logger_module.Logger("created_after_file_log").get()
    assert any(
        type(h) is logging.StreamHandler for h in log.handlers
    ), "console handler was suppressed by the root file handler"

    log.warning("reaches both sinks")
    for h in root.handlers:
        h.flush()
    assert "reaches both sinks" in target.read_text()
