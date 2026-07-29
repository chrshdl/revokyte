"""Automotive-style window layering.

What is on screen is a stack of windows composited in fixed z-order
layers. The BASE layer is the StateManager's active state (the
full-screen app windows: dashboard, setup, ...). Overlay windows —
notification cards, alerts — live in their own layers above it and are
composited by the WindowManager every frame, after the base has drawn.

This is what makes overlays safe over a *live* base: the base keeps
updating and drawing normally, and whenever one of its dirty rects
touches an overlay, the overlay is re-composited on top. Overlays are
never part of a view's sprite groups, so no widget can ever draw over
them. The most safety-relevant layer sits topmost (SYSTEM_ALERT), above
app content.

Layers only settle *pixels*, though — which window covers which. Whether
two windows may be up at the same time is a separate question, and the
WindowManager arbitrates it (`_arbitrate`), the way AAOS's
``OverlayViewGlobalStateController`` does for the views sharing its
``SystemUIOverlayWindow``: the topmost visible window owns the policy, and
a window it occludes is *withdrawn* — not drawn, no events — rather than
merely covered. Withdrawal is stateless and recomputed every frame, so the
occluded window comes back by itself when the occluder goes; it is a
deferral, never a dismissal. Two opt-ins express it, mirroring that class's
predicates: `occludes_below` (this window suppresses everything under it)
and `show_when_occluded` (this window survives someone else's occlusion).
Both default off, so a lone overlay behaves exactly as before.

A window therefore has two notions of being up: `visible` is its own
request, and `showing` is what survived arbitration. Anything that has to
match the pixels — compositing, event routing, dirty-sprite bookkeeping —
keys off `showing`.
"""

from __future__ import annotations

from enum import IntEnum

import pygame


class WindowLayer(IntEnum):
    # The active state's view. Not an overlay — drawn by the StateManager.
    BASE = 0
    # Heads-up cards (e.g. an extension's notification popup).
    NOTIFICATION = 10
    # Reserved topmost layer for safety-relevant overlays.
    SYSTEM_ALERT = 20


def _subtract(rect: pygame.Rect, covered: list[pygame.Rect]) -> list[pygame.Rect]:
    """Split `rect` into the pieces not covered by any rect in `covered`."""
    pieces = [rect]
    for other in covered:
        remaining = []
        for piece in pieces:
            clip = piece.clip(other)
            if clip.width == 0 or clip.height == 0:
                remaining.append(piece)
                continue
            remaining.extend(
                r
                for r in (
                    pygame.Rect(
                        piece.left, piece.top, piece.width, clip.top - piece.top
                    ),
                    pygame.Rect(
                        piece.left, clip.bottom, piece.width, piece.bottom - clip.bottom
                    ),
                    pygame.Rect(
                        piece.left, clip.top, clip.left - piece.left, clip.height
                    ),
                    pygame.Rect(
                        clip.right, clip.top, piece.right - clip.right, clip.height
                    ),
                )
                if r.width > 0 and r.height > 0
            )
        pieces = remaining
    return pieces


class OverlayWindow:
    """A composited window above the base layer.

    Subclasses own DirtySprites (`sprites`, bottom-to-top), decide their
    own `visible`, and may consume events. Drawing is handled here: the
    window's own dirty sprites are repainted, and wherever the base drew
    underneath this frame the sprite stack is re-composited — each pixel
    at most once per frame, because a translucent sprite (e.g. a dim
    scrim) re-blitted over pixels it already dimmed darkens them a bit
    more every frame, making low-rate base widgets visibly pulse.
    """

    layer = WindowLayer.NOTIFICATION

    # While this window is the topmost visible one, everything below it is
    # withdrawn. For a window that must be read and acted on alone — a
    # safety alert — rather than sharing the screen with a card.
    occludes_below = False
    # Opt out of the above: this window stays up under an occluder. For
    # something that has to remain legible no matter what is on top of it
    # (a persistent status strip), not for anything that can wait.
    show_when_occluded = False

    def __init__(self):
        self.sprites: list[pygame.sprite.DirtySprite] = []
        # Set by the WindowManager every frame; never by the window itself.
        self.occluded = False

    @property
    def visible(self) -> bool:
        """Whether this window *wants* to be up."""
        return False

    @property
    def showing(self) -> bool:
        """Whether it actually is — its request, after arbitration."""
        return self.visible and not self.occluded

    @property
    def rect(self) -> pygame.Rect | None:
        rects = [s.rect for s in self.sprites]
        if not rects:
            return None
        return rects[0].unionall(rects[1:])

    def update(self, dt: float) -> None:
        pass

    def handle_event(self, event) -> bool:
        return False

    def draw(self, surface, below_rects) -> list[pygame.Rect]:
        if not self.showing:
            return []
        rect = self.rect
        if rect is None:
            return []

        painted: list[pygame.Rect] = []

        # The window's own dirty sprites: repaint each together with
        # whatever is stacked above it. Sprites below it are already
        # current on the surface, so transparent pixels stay correct.
        for i, sprite in enumerate(self.sprites):
            if not sprite.visible:
                continue
            if sprite.dirty:
                pieces = _subtract(sprite.rect, painted)
                self._composite(surface, pieces, start=i)
                painted.extend(pieces)
            sprite.dirty = 0

        # Regions the base repainted underneath: re-composite the full
        # stack there, skipping anything painted above — never twice.
        for below in below_rects:
            clip = below.clip(rect)
            if clip.width and clip.height:
                pieces = _subtract(clip, painted)
                self._composite(surface, pieces, start=0)
                painted.extend(pieces)

        return painted

    def _composite(self, surface, areas, start: int) -> None:
        """Blit the sprite stack from z-index `start` up, clipped to `areas`."""
        for area in areas:
            for sprite in self.sprites[start:]:
                if not sprite.visible:
                    continue
                part = area.clip(sprite.rect)
                if part.width and part.height:
                    surface.blit(
                        sprite.image,
                        part.topleft,
                        part.move(-sprite.rect.left, -sprite.rect.top),
                    )


class WindowManager:
    """The compositor and the arbiter: base state first, then overlays in
    layer order, minus any the topmost one occludes.

    Events run the opposite way — topmost overlay first — so an overlay
    can own its input before the base sees it.
    """

    def __init__(self, state_manager):
        self.state_manager = state_manager
        self._windows: list[OverlayWindow] = []
        self._was_showing: dict[int, bool] = {}

    @property
    def is_running(self) -> bool:
        return self.state_manager.is_running

    def add_window(self, window: OverlayWindow) -> None:
        self._windows.append(window)
        # Stable, so windows sharing a layer keep their registration order:
        # last added is topmost, and stays topmost across re-sorts.
        self._windows.sort(key=lambda w: w.layer)

    def _arbitrate(self) -> None:
        """Decide which visible windows are actually up this frame.

        Only the topmost visible window is asked whether it occludes, so a
        lower layer can never suppress a higher one — a NOTIFICATION cannot
        withdraw a SYSTEM_ALERT, whichever order they light up in. Recomputed
        from scratch every frame: nothing latches, so a withdrawn window
        returns the moment the occluder stops asking to be shown.
        """
        visible = [w for w in self._windows if w.visible]
        top = visible[-1] if visible else None
        occluding = top is not None and top.occludes_below
        for window in self._windows:
            window.occluded = bool(
                occluding and window is not top and not window.show_when_occluded
            )

    def handle_event(self, event) -> bool:
        # Against last frame's arbitration — the main loop pumps events
        # before update(), and what the user just touched is what was on
        # screen. An occluded window is skipped rather than asked: a
        # withdrawn modal must not still be swallowing taps it can't
        # explain, so this holds even for a window that only checks
        # `visible` itself.
        for window in reversed(self._windows):
            if window.occluded:
                continue
            if window.handle_event(event):
                return True
        return self.state_manager.handle_event(event)

    def update(self, dt: float) -> None:
        self.state_manager.update(dt)
        # Before the windows update, so each one's own rising/falling-edge
        # bookkeeping sees the arbitrated answer and not its bare request.
        self._arbitrate()
        for window in self._windows:
            window.update(dt)

    def draw(self, surface) -> list[pygame.Rect]:
        # Again here: draw() is also called on its own (previews, tests),
        # and nothing a window's visibility depends on changes between
        # update() and draw() within a frame, so this is idempotent.
        self._arbitrate()

        # An overlay that just went away leaves stale pixels the base
        # doesn't know about — repaint the base before drawing this frame.
        # Withdrawn by arbitration counts: the pixels are just as stale
        # whether the window stopped asking or was overruled.
        for window in self._windows:
            was = self._was_showing.get(id(window), False)
            if was and not window.showing:
                self.state_manager.request_full_paint()
            self._was_showing[id(window)] = window.showing

        rects = self.state_manager.draw(surface) or []
        for window in self._windows:
            rects.extend(window.draw(surface, rects))
        return rects
