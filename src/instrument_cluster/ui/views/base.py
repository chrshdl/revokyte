from abc import ABC, abstractmethod

import pygame


class View(ABC):
    """Contract for all state views.

    draw() and full_paint() are the rendering contract the StateManager depends on.
    update() and handle_event() have default no-op implementations because their
    signatures vary across views (some take a bus arg, some don't).
    draw_static_elements() is optional — views that draw decorations onto the
    background surface override it.
    """

    background_color: tuple

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
