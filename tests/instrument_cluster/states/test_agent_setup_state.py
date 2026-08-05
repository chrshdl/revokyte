"""Choosing a feed with a PC agent leads with the pairing screen."""

import pytest

from instrument_cluster.addons.feeds import telemetry_choices
from instrument_cluster.config import ConfigManager
from instrument_cluster.states.agent_setup_state import AgentSetupState
from instrument_cluster.states.enter_ip_state import EnterIPState
from instrument_cluster.states.setup_state import SetupState
from instrument_cluster.telemetry.mode import TelemetryMode


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


def _choice(feed_id: str):
    return next(c for c in telemetry_choices() if c.feed_id == feed_id)


def _select(feed_id: str, on_pi: bool, monkeypatch):
    monkeypatch.setattr(
        "instrument_cluster.peripherals.display.is_raspberry_pi", lambda: on_pi
    )
    manager = _FakeStateManager()
    state = SetupState(manager)
    manager.state = state
    state.on_telemetry_selected(_choice(feed_id))
    return manager.changed_to


def test_acc_opens_the_pairing_screen_on_the_appliance(monkeypatch):
    # The agent path needs no IP typed on the cluster at all — the game PC
    # sends to us — so the pairing screen replaces IP entry as the next view.
    assert isinstance(_select("acc", on_pi=True, monkeypatch=monkeypatch),
                      AgentSetupState)


def test_a_feed_without_an_agent_still_goes_to_ip_entry(monkeypatch):
    assert isinstance(_select("granturismo", on_pi=True, monkeypatch=monkeypatch),
                      EnterIPState)


def test_desktop_skips_the_pairing_screen(monkeypatch):
    # Desktop builds read the feed in-process; there is no appliance to pair
    # a PC agent with.
    assert isinstance(_select("acc", on_pi=False, monkeypatch=monkeypatch),
                      EnterIPState)


def test_basic_setup_falls_back_to_ip_entry(monkeypatch):
    state = _select("acc", on_pi=True, monkeypatch=monkeypatch)
    manager = state.state_manager
    state.on_basic_released()
    fallback = manager.changed_to
    assert isinstance(fallback, EnterIPState)
    assert fallback.descriptor.id == "acc"


def test_full_mode_listens_on_the_lan_interface(monkeypatch):
    # The sender is another machine, so a loopback bind would drop every
    # frame the agent sends.
    state = _select("acc", on_pi=True, monkeypatch=monkeypatch)
    state.apply_full_mode()
    config = ConfigManager.get_config()
    assert config.udp_host == "0.0.0.0"
    assert config.telemetry_mode == TelemetryMode.UDP.value
    assert config.telemetry_feed == "acc"
    assert config.telemetry_feed_version == state.descriptor.version


def test_exit_closes_the_pairing_window(monkeypatch):
    # The web server must not outlive the screen that explains it.
    state = _select("acc", on_pi=True, monkeypatch=monkeypatch)

    class _Server:
        stopped = False

        def stop(self):
            type(self).stopped = True

    state._server = _Server()
    state.exit()
    assert _Server.stopped
    assert state._server is None
