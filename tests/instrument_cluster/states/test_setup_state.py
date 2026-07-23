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
    """Mirrors the piece of the real StateManager contract that matters
    here: pop_state() calls exit() on the state being popped — that's where
    SetupState queues its settings flush."""

    def __init__(self):
        self.popped = False
        self.state = None

    def pop_state(self):
        self.popped = True
        if self.state is not None:
            self.state.exit()


def _make_state() -> SetupState:
    manager = _FakeStateManager()
    state = SetupState(manager)
    manager.state = state
    return state


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


@pytest.fixture
def write_calls(monkeypatch):
    """Patches the config writer's disk I/O so tests can assert on it
    without touching the real filesystem. The write happens on the real
    background writer thread — call ConfigManager.flush() before asserting
    (that also makes the no-write cases deterministic)."""
    calls = []
    monkeypatch.setattr(
        "instrument_cluster.config._write_config_dict",
        lambda config_dict, path: calls.append(config_dict),
    )
    return calls


def test_selecting_a_dropdown_option_does_not_write_to_disk(config_path, write_calls):
    state = _make_state()
    state.handle_event(_selected_event(DiffReferenceMode.FASTEST))

    ConfigManager.flush(timeout=2)
    assert write_calls == []
    # applied live in-memory though (e.g. so DeltaSignal reacts immediately)
    assert ConfigManager.get_config().diff_reference_mode == DiffReferenceMode.FASTEST.value


def test_leaving_the_view_persists_exactly_once_when_changed(config_path, write_calls):
    state = _make_state()
    state.handle_event(_selected_event(DiffReferenceMode.FASTEST))
    state.handle_event(_selected_event(DiffReferenceMode.PREVIOUS))
    state.handle_event(_selected_event(DiffReferenceMode.FASTEST))
    ConfigManager.flush(timeout=2)
    assert write_calls == []

    state.handle_event(_back_event())

    ConfigManager.flush(timeout=2)
    assert len(write_calls) == 1
    assert state.state_manager.popped


def test_toggling_status_lights_applies_live_and_persists_on_exit(
    config_path, write_calls
):
    state = _make_state()
    state.handle_event(_status_lights_event(True))

    # applied live in-memory (DashboardState rebuilds its layout on resume)
    assert ConfigManager.get_config().status_lights is True
    ConfigManager.flush(timeout=2)
    assert write_calls == []

    state.handle_event(_back_event())
    ConfigManager.flush(timeout=2)
    assert len(write_calls) == 1


def test_toggling_status_lights_back_and_forth_does_not_write(config_path, write_calls):
    state = _make_state()
    state.handle_event(_status_lights_event(True))
    state.handle_event(_status_lights_event(False))
    state.handle_event(_back_event())

    ConfigManager.flush(timeout=2)
    assert write_calls == []


def test_leaving_the_view_without_changes_does_not_write(config_path, write_calls):
    state = _make_state()
    # reselect the same value that was already selected
    state.handle_event(_selected_event(DiffReferenceMode.PREVIOUS))
    state.handle_event(_back_event())

    ConfigManager.flush(timeout=2)
    assert write_calls == []
    assert state.state_manager.popped


def test_brightness_applies_in_memory_and_survives_any_exit_path(
    config_path, write_calls
):
    """Regression: brightness used to live only in SetupState's own
    current_brightness until the back button, so leaving via change_state
    (e.g. selecting a telemetry feed) dropped it. It must now hit the
    in-memory config immediately and be flushed by exit() alone — the
    change_state path calls exit() without on_back_released."""
    state = _make_state()
    state.adjust_brightness(+10)

    assert ConfigManager.get_config().brightness == 60
    ConfigManager.flush(timeout=2)
    assert write_calls == []

    state.exit()  # what StateManager.change_state does to the outgoing state

    ConfigManager.flush(timeout=2)
    assert len(write_calls) == 1
    assert write_calls[0]["brightness"] == 60
