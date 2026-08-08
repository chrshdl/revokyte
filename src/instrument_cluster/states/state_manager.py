import pygame

from ..core.vehicle.vehicle_bus import VehicleBus
from ..logger import Logger
from ..states.state import State
from ..states.state_types import SupportsStateChange


class StateManager(SupportsStateChange):
    def __init__(
        self,
        screen: pygame.Surface,
        vehicle_bus: VehicleBus,
        initial_state: State | None = None,
    ):
        self.logger = Logger(__class__.__name__).get()
        self.is_running = True
        self._screen = screen
        self.vehicle_bus = vehicle_bus
        self._stack: list[State] = []
        self._pending_rects: list[pygame.Rect] = []

        if initial_state is not None:
            self.push_state(initial_state)

    @property
    def current_state(self) -> State | None:
        return self._stack[-1] if self._stack else None

    def handle_event(self, event: pygame.event.Event) -> bool:
        # Only the current state sees input. Events used to fall through the
        # stack until some state returned True — but views return False for
        # raw touches, so every covered state hit-tested taps meant for the
        # screen above it. On the 7" panel the Wi-Fi keyboard ghost-pressed
        # the paused Setup screen's rows underneath: a tap on OK could make
        # Setup push a *second* WifiSetupState (opening on the scan list)
        # while the first one's connect succeeded into a state nobody polls,
        # and typing a password flipped Setup's status-lights toggle. A
        # paused state is covered, and covered widgets must not see taps.
        state = self.current_state
        if state is None:
            return False
        try:
            return bool(state.handle_event(event))
        except Exception as e:
            self.logger.error(f"handle_event error: {e}")
            return False

    def update(self, dt: float):
        s = self.current_state
        if s is None:
            return
        try:
            s.update(dt)
        except Exception:
            self.logger.error(
                "State %s crashed in update()", s.__class__.__name__, exc_info=True
            )

    def draw(self, surface: pygame.Surface):
        s = self.current_state
        if s is None:
            return []

        if self._pending_rects:
            try:
                s.full_paint(surface)
            except Exception as e:
                self.logger.error(f"full_paint error: {e}")
            rects = self._pending_rects
            self._pending_rects = []
            return rects

        return s.draw(surface) or []

    def request_full_paint(self):
        """Repaint the whole active state on the next draw — used by the
        window compositor when an overlay uncovers stale base pixels."""
        self._pending_rects = [self._screen.get_rect()]

    def change_state(self, new_state: State):
        if self._stack:
            top = self._stack.pop()
            try:
                top.exit()
            except Exception:
                self.logger.error("State %s crashed in exit()", top.__class__.__name__, exc_info=True)
        self.push_state(new_state)

    def push_state(self, state: State):
        top = self.current_state
        if top is not None:
            try:
                top.on_pause()
            except Exception as e:
                self.logger.error(f"on_pause error: {e}")
        state.state_manager = self
        self._stack.append(state)
        try:
            rects = state.enter(self._screen) or [self._screen.get_rect()]
            self._pending_rects = list(rects)
        except Exception as e:
            self.logger.error(f"state.enter error: {e}")

    def pop_state(self):
        if not self._stack:
            return
        top = self._stack.pop()
        try:
            top.exit()
        except Exception:
            self.logger.error("State %s crashed in exit()", top.__class__.__name__, exc_info=True)
        if self._stack:
            state = self._stack[-1]
            try:
                state.on_resume()
            finally:
                self._pending_rects = [self._screen.get_rect()]
