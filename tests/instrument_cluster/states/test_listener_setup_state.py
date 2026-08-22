"""Choosing a listener feed leads with the address screen, not IP entry."""

import pygame
import pytest

from instrument_cluster.addons.feeds import telemetry_choices
from instrument_cluster.config import ConfigManager
from instrument_cluster.states import listener_setup_state as module
from instrument_cluster.states.enter_ip_state import EnterIPState
from instrument_cluster.states.install_state import InstallState
from instrument_cluster.states.listener_setup_state import ListenerSetupState
from instrument_cluster.states.setup_state import SetupState
from instrument_cluster.telemetry.mode import TelemetryMode
from instrument_cluster.ui.events import BUTTON_BACK_RELEASED, LISTENER_CONTINUE_RELEASED


class _FakeStateManager:
    def __init__(self):
        self.state = None
        self.changed_to = None

    def change_state(self, state):
        self.changed_to = state

    def pop_state(self):
        if self.state is not None:
            self.state.exit()


@pytest.fixture(autouse=True)
def reset_manager():
    ConfigManager.reset()
    yield
    ConfigManager.reset()


@pytest.fixture
def screen():
    return pygame.Surface((1280, 720))


def _choice(feed_id: str):
    return next(c for c in telemetry_choices() if c.feed_id == feed_id)


def _select(feed_id: str):
    manager = _FakeStateManager()
    state = SetupState(manager)
    manager.state = state
    state.on_telemetry_selected(_choice(feed_id))
    return manager.changed_to


def test_listener_feed_opens_the_address_screen():
    assert isinstance(_select("forza-horizon-6"), ListenerSetupState)


def test_a_connector_feed_still_goes_to_ip_entry():
    assert isinstance(_select("granturismo"), EnterIPState)


def test_shows_this_devices_own_address_and_configured_port(screen, monkeypatch):
    monkeypatch.setattr(module, "cluster_lan_ip", lambda: "192.168.1.42")

    state = _select("forza-horizon-6")
    state.enter(screen)

    assert state.view.address_label.text == "192.168.1.42:7300"


def test_no_network_shows_an_error_instead_of_a_blank_address(screen, monkeypatch):
    monkeypatch.setattr(module, "cluster_lan_ip", lambda: "")

    state = _select("forza-horizon-6")
    state.enter(screen)

    assert state.view.error_label.text == "No network connection"
    assert state.view.address_label.text == ""


def test_continue_installs_the_proxy_on_the_appliance(screen, monkeypatch):
    """FH6 has a direct_reader too (for desktop), but the appliance always
    installs the signed proxy tarball, same as every other feed."""
    monkeypatch.setattr(module, "cluster_lan_ip", lambda: "192.168.1.42")
    monkeypatch.setattr(module, "is_raspberry_pi", lambda: True)

    state = _select("forza-horizon-6")
    manager = state.state_manager
    state.enter(screen)

    state.handle_event(pygame.event.Event(LISTENER_CONTINUE_RELEASED))

    installed = manager.changed_to
    assert isinstance(installed, InstallState)
    assert installed.descriptor.id == "forza-horizon-6"
    assert installed.ip == "192.168.1.42"


def test_continue_reads_in_process_on_desktop(screen, monkeypatch):
    """Desktop has no proxy to install — same carve-out EnterIPState makes
    for any feed with a direct_reader — so Continue configures DIRECT mode
    and hands back to the dashboard instead."""
    monkeypatch.setattr(module, "cluster_lan_ip", lambda: "192.168.1.42")
    monkeypatch.setattr(module, "is_raspberry_pi", lambda: False)

    state = _select("forza-horizon-6")
    manager = state.state_manager
    state.enter(screen)

    state.handle_event(pygame.event.Event(LISTENER_CONTINUE_RELEASED))

    assert manager.changed_to is state, "no InstallState pushed"
    cfg = ConfigManager.get_config()
    assert cfg.telemetry_mode == TelemetryMode.DIRECT.value
    assert cfg.telemetry_feed == "forza-horizon-6"
    # Unused by Fh6DirectReader, but must be non-empty: satisfies
    # SignalPipeline._make_direct_reader's "no console IP configured" guard.
    assert cfg.direct_host == "192.168.1.42"


def test_continue_does_nothing_without_a_known_address(screen, monkeypatch):
    monkeypatch.setattr(module, "cluster_lan_ip", lambda: "")

    state = _select("forza-horizon-6")
    manager = state.state_manager
    state.enter(screen)

    state.handle_event(pygame.event.Event(LISTENER_CONTINUE_RELEASED))

    assert manager.changed_to is state, "still stuck on this screen, not installing blind"


def test_back_returns_to_setup(screen, monkeypatch):
    monkeypatch.setattr(module, "cluster_lan_ip", lambda: "192.168.1.42")

    state = _select("forza-horizon-6")
    manager = state.state_manager
    state.enter(screen)

    state.handle_event(pygame.event.Event(BUTTON_BACK_RELEASED))

    assert isinstance(manager.changed_to, SetupState)
