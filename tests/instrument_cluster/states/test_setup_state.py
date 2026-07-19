import json

import pygame
import pytest

from instrument_cluster.config import ConfigManager
from instrument_cluster.states.setup_state import SetupState
from instrument_cluster.telemetry.mode import DiffReferenceMode, TelemetryMode
from instrument_cluster.ui.events import (
    BUTTON_BACK_RELEASED,
    DIFF_REFERENCE_MODE_SELECTED,
    STATUS_LIGHTS_TOGGLED,
)


class _FakeStateManager:
    def __init__(self):
        self.popped = False

    def pop_state(self):
        self.popped = True


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


def _selected_event(mode) -> pygame.event.Event:
    return pygame.event.Event(DIFF_REFERENCE_MODE_SELECTED, {"mode": mode})


def _back_event() -> pygame.event.Event:
    return pygame.event.Event(BUTTON_BACK_RELEASED, {})


def _status_lights_event(checked: bool) -> pygame.event.Event:
    return pygame.event.Event(STATUS_LIGHTS_TOGGLED, {"checked": checked})


class _SynchronousThread:
    """Stand-in for threading.Thread that runs target() immediately, so
    tests can assert on persist()'s background write without a real race."""

    def __init__(self, target, daemon=None):
        self._target = target

    def start(self):
        self._target()


@pytest.fixture
def write_calls(monkeypatch):
    """Patches persist()'s actual (background-thread) disk I/O so tests can
    assert on it deterministically, without touching the real filesystem or
    racing a real thread."""
    calls = []
    monkeypatch.setattr(
        "instrument_cluster.config._write_config_dict",
        lambda config_dict, path: calls.append(path),
    )
    monkeypatch.setattr("instrument_cluster.config.threading.Thread", _SynchronousThread)
    return calls


def test_selecting_a_dropdown_option_does_not_write_to_disk(config_path, write_calls):
    state = SetupState(_FakeStateManager())
    state.handle_event(_selected_event(DiffReferenceMode.FASTEST))

    assert write_calls == []
    # applied live in-memory though (e.g. so DeltaSignal reacts immediately)
    assert ConfigManager.get_config().diff_reference_mode == DiffReferenceMode.FASTEST.value


def test_leaving_the_view_persists_exactly_once_when_changed(config_path, write_calls):
    state = SetupState(_FakeStateManager())
    state.handle_event(_selected_event(DiffReferenceMode.FASTEST))
    state.handle_event(_selected_event(DiffReferenceMode.PREVIOUS))
    state.handle_event(_selected_event(DiffReferenceMode.FASTEST))
    assert write_calls == []

    state.handle_event(_back_event())

    assert len(write_calls) == 1
    assert state.state_manager.popped


def test_toggling_status_lights_applies_live_and_persists_on_exit(
    config_path, write_calls
):
    state = SetupState(_FakeStateManager())
    state.handle_event(_status_lights_event(True))

    # applied live in-memory (DashboardState rebuilds its layout on resume)
    assert ConfigManager.get_config().status_lights is True
    assert write_calls == []

    state.handle_event(_back_event())
    assert len(write_calls) == 1


def test_toggling_status_lights_back_and_forth_does_not_write(config_path, write_calls):
    state = SetupState(_FakeStateManager())
    state.handle_event(_status_lights_event(True))
    state.handle_event(_status_lights_event(False))
    state.handle_event(_back_event())

    assert write_calls == []


def test_leaving_the_view_without_changes_does_not_write(config_path, write_calls):
    state = SetupState(_FakeStateManager())
    # reselect the same value that was already selected
    state.handle_event(_selected_event(DiffReferenceMode.PREVIOUS))
    state.handle_event(_back_event())

    assert write_calls == []
    assert state.state_manager.popped
