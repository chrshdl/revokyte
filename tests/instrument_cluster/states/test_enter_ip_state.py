"""Tests for the IP-entry state's two OK paths: install a proxy on the
appliance, configure the in-process reader on desktop."""

import json

import pygame
import pytest

from instrument_cluster.addons.feeds import feed_by_id
from instrument_cluster.config import ConfigManager
from instrument_cluster.states.enter_ip_state import EnterIPState
from instrument_cluster.states.install_state import InstallState
from instrument_cluster.telemetry.mode import TelemetryMode


class _FakeStateManager:
    def __init__(self):
        self.popped = False
        self.changed_to = None

    def pop_state(self):
        self.popped = True

    def change_state(self, state):
        self.changed_to = state


@pytest.fixture(autouse=True)
def isolated_config(tmp_path):
    ConfigManager.reset()
    ConfigManager.set_path(tmp_path / "config.json")
    (tmp_path / "config.json").write_text(json.dumps({}))
    yield
    ConfigManager.reset()


def _make_state(descriptor):
    manager = _FakeStateManager()
    state = EnterIPState(state_manager=manager, descriptor=descriptor)
    # A state has no view until enter() borrows one from the ViewRegistry.
    state.enter(pygame.Surface((1280, 720)))
    return manager, state


def test_desktop_gt7_ok_configures_direct_mode(monkeypatch):
    monkeypatch.setattr(
        "instrument_cluster.states.enter_ip_state.is_raspberry_pi", lambda: False
    )
    manager, state = _make_state(feed_by_id("granturismo"))
    state.view.textfield.set_text("192.168.1.50")

    assert state.on_ok_released() is True

    cfg = ConfigManager.get_config()
    assert cfg.telemetry_mode == TelemetryMode.DIRECT.value
    assert cfg.telemetry_feed == "granturismo"
    assert cfg.direct_host == "192.168.1.50"
    assert cfg.recent_connected[0] == "192.168.1.50"
    # Hands straight back to the dashboard — no install screen.
    assert manager.popped is True
    assert manager.changed_to is None


def test_appliance_gt7_ok_still_routes_to_the_installer(monkeypatch):
    monkeypatch.setattr(
        "instrument_cluster.states.enter_ip_state.is_raspberry_pi", lambda: True
    )
    manager, state = _make_state(feed_by_id("granturismo"))
    state.view.textfield.set_text("192.168.1.50")

    assert state.on_ok_released() is True

    assert isinstance(manager.changed_to, InstallState)
    assert ConfigManager.get_config().telemetry_mode != TelemetryMode.DIRECT.value


def test_desktop_acc_ok_configures_direct_mode(monkeypatch):
    monkeypatch.setattr(
        "instrument_cluster.states.enter_ip_state.is_raspberry_pi", lambda: False
    )
    manager, state = _make_state(feed_by_id("acc"))
    state.view.textfield.set_text("192.168.1.20")

    assert state.on_ok_released() is True

    cfg = ConfigManager.get_config()
    assert cfg.telemetry_mode == TelemetryMode.DIRECT.value
    assert cfg.telemetry_feed == "acc"
    assert cfg.direct_host == "192.168.1.20"
    assert manager.popped is True
    assert manager.changed_to is None


def test_desktop_proxy_only_feed_still_routes_to_the_installer(monkeypatch):
    """A feed with no in-process reader keeps the install flow even off the
    appliance (it isn't offered in the desktop dropdown, but the state must
    not misroute it)."""
    from dataclasses import replace

    monkeypatch.setattr(
        "instrument_cluster.states.enter_ip_state.is_raspberry_pi", lambda: False
    )
    proxy_only = replace(feed_by_id("acc"), direct_reader=None)
    manager, state = _make_state(proxy_only)
    state.view.textfield.set_text("192.168.1.20")

    assert state.on_ok_released() is True

    assert isinstance(manager.changed_to, InstallState)


def test_invalid_ip_does_nothing(monkeypatch):
    monkeypatch.setattr(
        "instrument_cluster.states.enter_ip_state.is_raspberry_pi", lambda: False
    )
    manager, state = _make_state(feed_by_id("granturismo"))
    state.view.textfield.set_text("999.1.2")

    assert state.on_ok_released() is True

    assert manager.popped is False
    assert manager.changed_to is None
    assert ConfigManager.get_config().telemetry_mode == TelemetryMode.DEMO.value
