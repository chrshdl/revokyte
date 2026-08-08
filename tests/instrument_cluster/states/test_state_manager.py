import pygame
import pytest

from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus
from instrument_cluster.states.state_manager import StateManager


class MockState:
    """Minimal State stub that records lifecycle calls."""

    def __init__(self):
        self.enter_calls = 0
        self.exit_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.state_manager = None

    def enter(self, screen):
        self.enter_calls += 1
        return [screen.get_rect()]

    def exit(self):
        self.exit_calls += 1

    def on_pause(self):
        self.pause_calls += 1

    def on_resume(self):
        self.resume_calls += 1

    def update(self, dt):
        pass

    def draw(self, surface):
        return []

    def full_paint(self, surface):
        pass

    def handle_event(self, event):
        return False

    def background_color(self):
        return (0, 0, 0)

    def draw_static_background(self, bg):
        pass


class CrashingState(MockState):
    """State whose update() always raises."""

    def update(self, dt):
        raise RuntimeError("boom")


@pytest.fixture
def screen():
    surface = pygame.display.get_surface()
    return surface if surface is not None else pygame.display.set_mode((100, 100))


@pytest.fixture
def bus():
    return VehicleBus()


@pytest.fixture
def manager(screen, bus):
    return StateManager(screen, bus)


# --- current_state ---


def test_current_state_empty_stack(manager):
    assert manager.current_state is None


def test_current_state_after_push(manager):
    state = MockState()
    manager.push_state(state)
    assert manager.current_state is state


# --- push_state ---


def test_push_calls_enter(manager, screen):
    state = MockState()
    manager.push_state(state)
    assert state.enter_calls == 1


def test_push_pauses_previous(manager):
    first = MockState()
    second = MockState()
    manager.push_state(first)
    manager.push_state(second)
    assert first.pause_calls == 1
    assert second.pause_calls == 0


def test_push_sets_state_manager_reference(manager):
    state = MockState()
    manager.push_state(state)
    assert state.state_manager is manager


def test_push_populates_pending_rects(manager):
    state = MockState()
    manager.push_state(state)
    assert len(manager._pending_rects) > 0


# --- pop_state ---


def test_pop_calls_exit_on_top(manager):
    state = MockState()
    manager.push_state(state)
    manager.pop_state()
    assert state.exit_calls == 1


def test_pop_resumes_previous(manager):
    first = MockState()
    second = MockState()
    manager.push_state(first)
    manager.push_state(second)
    manager.pop_state()
    assert first.resume_calls == 1


def test_pop_empty_stack_is_noop(manager):
    manager.pop_state()  # should not raise


def test_pop_restores_current_state(manager):
    first = MockState()
    second = MockState()
    manager.push_state(first)
    manager.push_state(second)
    manager.pop_state()
    assert manager.current_state is first


# --- change_state ---


def test_change_state_exits_top(manager):
    first = MockState()
    second = MockState()
    manager.push_state(first)
    manager.change_state(second)
    assert first.exit_calls == 1


def test_change_state_enters_new(manager):
    first = MockState()
    second = MockState()
    manager.push_state(first)
    manager.change_state(second)
    assert second.enter_calls == 1


def test_change_state_replaces_current(manager):
    first = MockState()
    second = MockState()
    manager.push_state(first)
    manager.change_state(second)
    assert manager.current_state is second
    assert len(manager._stack) == 1


# --- update ---


def test_update_does_not_crash_on_state_error(manager):
    """A crashing state must be logged, not propagated."""
    state = CrashingState()
    manager.push_state(state)
    manager.update(0.016)  # must not raise


def test_update_noop_on_empty_stack(manager):
    manager.update(0.016)  # must not raise


# --- draw ---


def test_draw_returns_pending_rects_on_first_frame(manager, screen):
    state = MockState()
    manager.push_state(state)
    rects = manager.draw(screen)
    assert isinstance(rects, list)
    assert len(rects) > 0


def test_draw_clears_pending_rects_after_full_paint(manager, screen):
    state = MockState()
    manager.push_state(state)
    manager.draw(screen)
    assert manager._pending_rects == []


def test_draw_returns_empty_on_empty_stack(manager, screen):
    assert manager.draw(screen) == []


# --- handle_event ---


def test_handle_event_returns_false_when_nothing_handles(manager):
    state = MockState()
    manager.push_state(state)
    event = pygame.event.Event(pygame.USEREVENT)
    assert manager.handle_event(event) is False


def test_handle_event_returns_true_when_handled(manager):
    class ConsumingState(MockState):
        def handle_event(self, event):
            return True

    state = ConsumingState()
    manager.push_state(state)
    event = pygame.event.Event(pygame.USEREVENT)
    assert manager.handle_event(event) is True


def test_handle_event_never_reaches_a_covered_state(manager):
    # A paused state is covered, and covered widgets must not see taps.
    # Events used to fall through the stack when the top state returned
    # False; views return False for raw touches, so a tap on the Wi-Fi
    # keyboard also hit-tested the Setup screen underneath — on the 7"
    # panel that ghost-pressed Setup's rows (pushing a second Wi-Fi setup
    # state mid-connect) and flipped its status-lights toggle while a
    # password was being typed.
    class RecordingState(MockState):
        def __init__(self):
            super().__init__()
            self.seen = []

        def handle_event(self, event):
            self.seen.append(event)
            return False  # decline, like every view does for raw touches

    below, top = RecordingState(), RecordingState()
    manager.push_state(below)
    manager.push_state(top)

    event = pygame.event.Event(pygame.FINGERUP, x=0.5, y=0.5)
    assert manager.handle_event(event) is False
    assert top.seen == [event]
    assert below.seen == []  # covered: never offered the event


def test_handle_event_survives_a_crashing_state(manager):
    class CrashingState(MockState):
        def handle_event(self, event):
            raise RuntimeError("boom")

    manager.push_state(CrashingState())
    event = pygame.event.Event(pygame.USEREVENT)
    assert manager.handle_event(event) is False  # logged, not raised
