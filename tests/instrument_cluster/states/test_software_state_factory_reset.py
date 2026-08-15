"""Two-tap factory-reset confirmation in SoftwareState (moved here
from Setup together with the row)."""

import json

import pygame
import pytest

from instrument_cluster.config import ConfigManager
from instrument_cluster.states.software_state import SoftwareState
from instrument_cluster.telemetry.mode import DiffReferenceMode, TelemetryMode
from instrument_cluster.ui.events import FACTORY_RESET_RELEASED


class _FakeStateManager:
    def __init__(self):
        self.state = None

    def pop_state(self):
        if self.state is not None:
            self.state.exit()


@pytest.fixture(autouse=True)
def reset_manager():
    ConfigManager.reset()
    yield
    ConfigManager.reset()


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "telemetry_mode": TelemetryMode.DEMO.value,
                "diff_reference_mode": DiffReferenceMode.PREVIOUS.value,
                "brightness": 50,
            }
        )
    )
    ConfigManager.set_path(path)
    return path


def _make_state():
    manager = _FakeStateManager()
    state = SoftwareState(manager)
    manager.state = state
    return state


def _reset_event():
    return pygame.event.Event(FACTORY_RESET_RELEASED, {})


@pytest.fixture
def spy_reset(monkeypatch):
    """Replace the destructive action with a spy so nothing is deleted."""
    calls = []
    monkeypatch.setattr(
        "instrument_cluster.core.system.factory_reset.perform_factory_reset",
        lambda *a, **k: calls.append(True),
    )
    return calls


def test_first_tap_arms_without_resetting(config_path, spy_reset):
    state = _make_state()
    handled = state.handle_event(_reset_event())

    assert handled is True
    assert state._factory_reset_armed_s > 0.0
    assert spy_reset == []  # not yet


def test_second_tap_while_armed_performs_reset(config_path, spy_reset):
    state = _make_state()
    state.handle_event(_reset_event())  # arm
    state.handle_event(_reset_event())  # confirm

    assert spy_reset == [True]
    assert state._factory_reset_armed_s == 0.0  # disarmed after firing


def test_arm_times_out_and_disarms(config_path, spy_reset):
    state = _make_state()
    state.handle_event(_reset_event())
    assert state._factory_reset_armed_s > 0.0

    # Advance past the arm window.
    state.update(SoftwareState.FACTORY_RESET_ARM_TIMEOUT_S + 0.1)

    assert state._factory_reset_armed_s == 0.0
    # A subsequent single tap only re-arms; it must not reset.
    state.handle_event(_reset_event())
    assert spy_reset == []
    assert state._factory_reset_armed_s > 0.0


def test_leaving_the_screen_disarms(config_path, spy_reset):
    state = _make_state()
    state.handle_event(_reset_event())
    assert state._factory_reset_armed_s > 0.0

    state.exit()

    assert state._factory_reset_armed_s == 0.0
    assert spy_reset == []


def test_reset_failure_does_not_propagate(config_path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(
        "instrument_cluster.core.system.factory_reset.perform_factory_reset", _boom
    )
    state = _make_state()
    state.handle_event(_reset_event())  # arm
    # Confirming tap: the action raises, but the HMI must stay alive.
    handled = state.handle_event(_reset_event())
    assert handled is True
