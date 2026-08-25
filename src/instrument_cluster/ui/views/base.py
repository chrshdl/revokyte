from abc import ABC, abstractmethod

import pygame


class View(ABC):
    """Contract for all state views.

    draw() and full_paint() are the rendering contract the StateManager depends on.
    update() and handle_event() have default no-op implementations because their
    signatures vary across views (some take a bus arg, some don't).
    draw_static_elements() is optional — views that draw decorations onto the
    background surface override it.

    build() and reset() split construction from rebinding. A view is built once
    and lives for the whole process; every entry into the owning state rebinds it
    through reset(). Everything expensive — widgets, surfaces, fonts — belongs in
    build() (or __init__, which build() defaults to complementing); reset() must
    allocate nothing.
    """

    background_color: tuple

    def build(self) -> None:
        """Create every widget and surface. Called once, by the ViewRegistry,
        after the display exists and before the first frame. No frame budget
        applies here."""

    def reset(self, ctx=None) -> None:
        """Rebind data and clear transient state so the view is indistinguishable
        from a freshly built one. Called on every enter() and on_resume() of the
        owning state, with whatever that state's view_context() returned.

        A view that keeps scroll offsets, open menus, typed text, or error labels
        must clear them here — a reused view outlives the state that dirtied it.
        """

    @staticmethod
    def release_presses(*groups) -> None:
        """Clear any stuck press across the given sprite groups or lists.

        Helper for reset(): a state transition fired from a button's own
        released handler leaves that button pressed, and a pooled view keeps
        it that way until someone taps it again.
        """
        for group in groups:
            if group is None:
                continue
            # Sprite groups, ButtonGroup, and plain lists all appear here;
            # only some of them are iterable.
            members = group.sprites() if hasattr(group, "sprites") else group
            for sprite in members:
                release = getattr(sprite, "release_press", None)
                if release is not None:
                    release()

    @abstractmethod
    def draw(
        self, surface: pygame.Surface, background: pygame.Surface | None
    ) -> list[pygame.Rect]: ...

    @abstractmethod
    def full_paint(
        self, surface: pygame.Surface, background: pygame.Surface | None
    ) -> None: ...

    def update(self, *args, **kwargs) -> None:
        pass

    def handle_event(self, event: pygame.event.Event) -> bool:
        return False

    def draw_static_elements(self, background_surface: pygame.Surface) -> None:
        pass
