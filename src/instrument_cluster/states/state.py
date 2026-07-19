from abc import ABC

import pygame

from ..states.state_types import SupportsStateChange


class State(ABC):
    def __init__(self, state_manager: SupportsStateChange | None = None):
        self.state_manager = state_manager
        self.screen: pygame.Surface | None = None
        self.background: pygame.Surface | None = None

        self.view = None
        self._pending_transition = None

    def draw(self, surface: pygame.Surface):
        if self.view:
            return self.view.draw(surface, self.background)
        return []

    def full_paint(self, surface: pygame.Surface):
        if self.background is not None:
            surface.blit(self.background, (0, 0))

        if self.view:
            self.view.full_paint(surface, self.background)

    def handle_event(self, event) -> bool:
        return bool(self.view and self.view.handle_event(event))

    def enter(self, screen: pygame.Surface):
        self.screen = screen

        self.background = pygame.Surface(screen.get_size()).convert()
        self.background.fill(self.background_color())
        self.draw_static_background(self.background)

        # StateManager.full_paint() will repaint, but blit once so the
        # screen isn't blank between enter() and the first draw cycle
        screen.blit(self.background, (0, 0))

        self.group = self.create_group()
        return [screen.get_rect()]

    def exit(self):
        pass

    def update(self, dt: float):
        if self.process_delayed_transition(self.state_manager):
            return

    def on_pause(self):
        pass

    def on_resume(self):
        pass

    def request_delayed_transition(self, next_state, delay_seconds):
        trigger_time = pygame.time.get_ticks() / 1000.0 + delay_seconds
        self._pending_transition = (next_state, trigger_time)

    def process_delayed_transition(self, state_manager: SupportsStateChange):
        if self._pending_transition:
            next_state, trigger_time = self._pending_transition
            if pygame.time.get_ticks() / 1000.0 >= trigger_time:
                self._pending_transition = None
                state_manager.change_state(next_state)
                return True
        return False
