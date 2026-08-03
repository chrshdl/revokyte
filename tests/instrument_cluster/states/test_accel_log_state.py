"""AccelLogState: the Dyno screen drives the recorder from the bus and
pops on Back. Headless construction + a few update ticks catch any
view/state API drift."""

from dataclasses import dataclass, field
from types import SimpleNamespace

import pygame
import pytest

from instrument_cluster.states.accel_log_state import AccelLogState
from instrument_cluster.core.engine_sim.accel_recorder import RecorderState
from instrument_cluster.ui.events import BUTTON_BACK_RELEASED


@dataclass
class FakeFrame:
    received_time: float = 1.0
    car_id: int = 37
    engine_rpm: float = 4200.0
    car_speed: float = 30.0
    throttle: float = 0.4
    current_gear: int = 3
    gear_ratios: list = field(default_factory=lambda: [3.2, 2.1, 1.6])
    wheels: object = None


class FakeStateManager:
    def __init__(self, frame):
        self.vehicle_bus = SimpleNamespace(frame=frame)
        self.popped = 0

    def pop_state(self):
        self.popped += 1


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("IC_CONFIG_PATH", str(tmp_path / "config.json"))
    manager = FakeStateManager(FakeFrame())
    return AccelLogState(manager), manager


def test_construction_and_update_ticks(state):
    accel_state, manager = state
    screen = pygame.display.set_mode((320, 180))
    accel_state.enter(screen)
    accel_state.full_paint(screen)

    for i in range(3):
        manager.vehicle_bus.frame = FakeFrame(received_time=1.0 + i * 0.016)
        accel_state.update(0.016)
        accel_state.draw(screen)

    assert accel_state.recorder.state == RecorderState.ARMED
    # The car line resolved against cars.json (id 37 = the Civic EG).
    assert "Civic" in accel_state.view.car_label.text


def test_no_live_car_shows_idle(state):
    accel_state, manager = state
    screen = pygame.display.set_mode((320, 180))
    accel_state.enter(screen)

    manager.vehicle_bus.frame = FakeFrame(car_id=-1)
    accel_state.update(0.016)
    assert accel_state.recorder.state == RecorderState.IDLE
    assert "no live car" in accel_state.view.car_label.text


def test_back_pops_the_state(state):
    accel_state, manager = state
    event = pygame.event.Event(BUTTON_BACK_RELEASED)
    assert accel_state.handle_event(event)
    assert manager.popped == 1


def test_runs_dir_derives_from_config_path(state, tmp_path):
    accel_state, _ = state
    assert accel_state.recorder.store.base_dir == tmp_path / "accel_runs"
