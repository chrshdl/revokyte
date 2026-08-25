from abc import ABC

import pygame

from ..states.state_types import SupportsStateChange
from ..ui.colors import Color
from ..ui.views.registry import views


class State(ABC):
    # The view this state shows. Declarative so the ViewRegistry can own the
    # instance for the life of the process — the state borrows it on enter()
    # and never constructs one.
    view_class = None

    def __init__(self, state_manager: SupportsStateChange | None = None):
        self.state_manager = state_manager
        self.screen: pygame.Surface | None = None
        self.background: pygame.Surface | None = None

        self.view = None
        self._pending_transition = None

    # ------------------------------------------------------------------
    # view contract
    # ------------------------------------------------------------------
    def view_context(self):
        """What the view needs rebound on every entry, handed to View.reset().

        None means "nothing to rebind" — the view's own reset() still runs, so
        transient state is cleared either way. States whose view used to take
        constructor arguments return them from here instead.
        """
        return None

    def background_color(self):
        # None only when the view failed to build (the registry fails open);
        # black keeps the screen coherent rather than raising mid-enter.
        if self.view is None:
            return Color.BLACK.rgb()
        return self.view.background_color

    def draw_static_background(self, bg):
        if self.view is not None:
            self.view.draw_static_elements(bg)

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------
    def draw(self, surface: pygame.Surface):
        if self.view:
            return self.view.draw(surface, self.background)
        return []

    def full_paint(self, surface: pygame.Surface):
        # No background blit here: every view blits (or fills over) the
        # background itself inside full_paint, so doing it again would cost a
        # second full-screen blit per repaint for nothing.
        if self.view:
            self.view.full_paint(surface, self.background)

    def handle_event(self, event) -> bool:
        return bool(self.view and self.view.handle_event(event))

    def enter(self, screen: pygame.Surface):
        self.screen = screen

        # Borrow the shared view and rebind it. Both happen here rather than in
        # __init__ because change_state() constructs the incoming state *before*
        # exiting the outgoing one — acquiring at construction would let the new
        # state reset a view the old one is still drawing.
        self.view = views.acquire(self.view_class, borrower=self)
        if self.view is not None:
            self.view.reset(self.view_context())
        self.repaint_background()

        # StateManager.full_paint() will repaint, but blit once so the
        # screen isn't blank between enter() and the first draw cycle
        screen.blit(self.background, (0, 0))

        return [screen.get_rect()]

    def repaint_background(self) -> None:
        """Fill the background and re-bake this state's static decorations.

        Called from enter() and on_resume() alike. The resume half is what
        makes one shared surface safe: a state stacked underneath keeps a
        reference to the same surface the screen above painted over, so it
        has to re-derive it rather than trust what it finds there.
        """
        manager = self.state_manager
        provider = getattr(manager, "background", None)
        if callable(provider):
            self.background = provider(self.background_color())
        else:
            # No manager (a state built in isolation, e.g. in a test or a
            # preview tool). Fall back to a private surface.
            if self.background is None and self.screen is not None:
                self.background = pygame.Surface(self.screen.get_size()).convert()
            if self.background is None:
                return
            self.background.fill(self.background_color())
        self.draw_static_background(self.background)

    def exit(self):
        views.release(self.view_class, borrower=self)

    def update(self, dt: float):
        if self.process_delayed_transition(self.state_manager):
            return

    def on_pause(self):
        pass

    def on_resume(self):
        # Resuming is a fresh entry as far as the view is concerned: the state
        # above may have changed the config the view renders, and it painted
        # its own chrome onto the background surface we share with it.
        if self.view is not None:
            self.view.reset(self.view_context())
        self.repaint_background()

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
