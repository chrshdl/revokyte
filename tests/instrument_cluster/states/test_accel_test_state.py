"""The Testing & Validation screen's wiring.

The timer's own arithmetic is covered in
``core/vehicle/test_accel_timer.py``; what is asserted here is the part the
driver reads and touches — that a dead link is not mistaken for a car
waiting at the line, that the status line says which of those it is, and
that the two controls do what their labels promise.
"""

import pygame
import pytest

from instrument_cluster.config import ConfigManager
from instrument_cluster.core.vehicle.accel_timer import TimerState
from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus
from instrument_cluster.states.accel_test_state import AccelTestState
from instrument_cluster.states.state_manager import StateManager
from instrument_cluster.telemetry.models import Flags, TelemetryFrame
from instrument_cluster.ui.events import (
    ACCEL_DISTANCE_SELECTED,
    ACCEL_RESET_RELEASED,
    ACCEL_TEST_RELEASED,
    BUTTON_BACK_RELEASED,
)
from instrument_cluster.ui.views.registry import views

HZ = 60.0


class _Clock:
    """A virtual receive clock, so a pull runs in no time at all."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def state(tmp_path):
    ConfigManager.set_path(tmp_path / "config.json")
    ConfigManager.reset()
    views.clear()

    screen = pygame.Surface((1280, 720))
    manager = StateManager(screen, VehicleBus())
    state = AccelTestState(manager)
    state._clock = _Clock()
    manager.push_state(state)
    try:
        yield state
    finally:
        manager.pop_state()
        views.clear()


def _publish(state, speed, *, car_on_track=True, stale=False):
    """Put one fresh frame on the bus and run a frame of the state."""
    clock = state._clock
    clock.t += 1 / HZ
    state.bus.frame = TelemetryFrame(
        car_id=1461,
        received_time=clock.t,
        car_speed=speed,
        flags=Flags(car_on_track=car_on_track),
    )
    state.bus.signals["telemetry_stale"] = stale
    state.update(1 / HZ)


def _status(state) -> str:
    return state.view.status_label.text


def test_a_stale_link_is_not_a_car_waiting_at_the_line(state):
    """Readers hold their last frame forever, so a dead link *is* a
    stationary car on the wire. Arming on it would leave the screen saying
    Ready at a console that has been asleep for an hour."""
    for _ in range(30):
        _publish(state, 0.0, stale=True)

    assert state.timer.state == TimerState.NO_SIGNAL
    assert _status(state) == "Waiting for telemetry"


def test_a_standing_car_arms_and_says_so(state):
    for _ in range(30):
        _publish(state, 0.0)

    assert state.timer.state == TimerState.READY
    assert _status(state) == "Ready — launch for 400 m"


def test_the_status_line_counts_the_distance_out_during_a_run(state):
    for _ in range(30):
        _publish(state, 0.0)
    for _ in range(60):
        _publish(state, 20.0)

    assert state.timer.state == TimerState.RUNNING
    assert _status(state).endswith("/ 400 m")
    assert float(state.view.time_label.text) > 0.0


def test_a_finished_run_reports_the_time_and_the_speed_at_the_line(state):
    ConfigManager.set_accel_test_distance(100, persist=False)
    state.timer.set_target(100)

    for _ in range(30):
        _publish(state, 0.0)
    for i in range(600):
        _publish(state, 5.0 * i / HZ)
        if state.timer.state == TimerState.DONE:
            break

    assert state.timer.state == TimerState.DONE
    assert float(state.view.time_label.text) == pytest.approx(6.22, abs=0.05)
    assert _status(state).startswith("100 m at ")


def test_reset_zeroes_the_clock_on_screen(state):
    for _ in range(30):
        _publish(state, 0.0)
    for _ in range(60):
        _publish(state, 20.0)
    assert float(state.view.time_label.text) > 0.0

    state.handle_event(pygame.event.Event(ACCEL_RESET_RELEASED))
    _publish(state, 20.0)

    assert float(state.view.time_label.text) == 0.0


def test_choosing_a_distance_applies_it_live_and_remembers_it(state):
    state.handle_event(pygame.event.Event(ACCEL_DISTANCE_SELECTED, {"mode": 200}))

    assert state.timer.target_m == 200
    assert ConfigManager.get_config().accel_test_distance == 200

    for _ in range(30):
        _publish(state, 0.0)
    assert _status(state) == "Ready — launch for 200 m"


def test_the_remembered_distance_is_on_screen_when_the_screen_opens(state, tmp_path):
    ConfigManager.set_accel_test_distance(300, persist=False)

    reopened = AccelTestState(state.state_manager)
    reopened._clock = _Clock()
    state.state_manager.push_state(reopened)
    try:
        assert reopened.timer.target_m == 300
        assert reopened.view.distance_dropdown.text == "300 m"
    finally:
        state.state_manager.pop_state()


def test_a_voided_run_says_why_before_falling_back_to_the_live_state(state):
    for _ in range(30):
        _publish(state, 0.0)
    for _ in range(60):
        _publish(state, 20.0)

    for _ in range(20):  # a spin: back to a standstill mid-run
        _publish(state, 0.0)

    assert _status(state) == "Run voided — run stopped"

    for _ in range(int(AccelTestState.NOTE_HOLD_S * HZ) + 2):
        _publish(state, 0.0)

    assert _status(state) == "Ready — launch for 400 m"


def test_the_setup_row_opens_the_screen_and_back_returns_to_it(tmp_path):
    """The row is the only way in, and Setup has to be underneath when the
    driver comes back out — pushed, not switched to."""
    from instrument_cluster.states.setup_state import SetupState

    ConfigManager.set_path(tmp_path / "config.json")
    ConfigManager.reset()
    views.clear()

    manager = StateManager(pygame.Surface((1280, 720)), VehicleBus())
    manager.push_state(SetupState(manager))
    try:
        manager.handle_event(pygame.event.Event(ACCEL_TEST_RELEASED))
        assert isinstance(manager.current_state, AccelTestState)

        manager.handle_event(pygame.event.Event(BUTTON_BACK_RELEASED))
        assert isinstance(manager.current_state, SetupState)
    finally:
        manager.pop_state()
        views.clear()
