"""Shared draw path for the settings screens with a scrollable row list.

`SetupView` and `SoftwareView` had this logic byte-for-byte duplicated. It
lives here because it is subtle in two ways worth stating once:

**Immediate mode is for motion, not for overflow.** While the offset is
changing, row positions move every frame and the dirty-rect diff cannot keep
up — it only repaints rects that were already dirty — so the viewport is
redrawn wholesale. But that was originally keyed on
``scrollbar.is_scrollable``, which merely means the content is taller than the
viewport. On the 7" panel it is *permanently* true (703 px of rows in a 498 px
viewport), so a stationary Setup screen paid a full-screen flush at 60 Hz:
6.42 ms/frame against 0.29 ms for a dirty-rect frame, 22x, measured on a Pi 4.
That is the 7% -> 20% CPU jump on entering Setup.

**Separators live in one of two places.** They sit between rows, so they have
to travel with them. While scrolling they are drawn per frame; at rest they are
baked into the background where the dirty-rect clear() restores them for free.
Switching between the two therefore has to re-bake the background and force one
full repaint to resync the layers' bookkeeping — see `_switch_scroll_mode`.
"""

from __future__ import annotations


class ScrollableRowsView:
    """Mixin for a view with `ui_layer`, `rows_layer`, `rows`, `scrollbar`
    and `horizontal_line`. Not a `View` subclass — the concrete views bring
    that, and their own construction."""

    # Whether the previous frame used the immediate-mode path. Class-level so
    # a view that never scrolls needs no __init__ change.
    _live_scroll = False
    # The offset the background's separators were last baked at, or None while
    # the live path owns them. Compared every settled frame so an offset that
    # moves without a mode switch cannot leave them stale.
    _baked_offset = None

    # ------------------------------------------------------------------
    # background
    # ------------------------------------------------------------------
    def draw_static_elements(self, background_surface) -> None:
        self.horizontal_line.draw(background_surface)
        if self._live_scroll:
            # Separators move with the rows while scrolling, so the live path
            # draws them per frame instead of baking them here.
            self._baked_offset = None
            return
        self._bake_separators(background_surface)
        self._baked_offset = self.scrollbar.offset

    def _bake_separators(self, surface) -> None:
        """Draw the separators for the *current* offset onto the background.

        Clipped to the viewport when scrolled: unclipped, the separators for
        rows parked above the list would land on the header.
        """
        scrollbar = self.scrollbar
        if not scrollbar.is_scrollable:
            self.rows.draw_static_elements(surface)
            return
        previous = surface.get_clip()
        surface.set_clip(scrollbar.viewport_rect())
        self.rows.draw_separators_live(surface, scrollbar.offset)
        surface.set_clip(previous)
        # Nothing repaints the thumb on the dirty-rect path, and its position
        # only changes with the offset — which re-bakes. So bake it too.
        scrollbar.draw(surface)

    # ------------------------------------------------------------------
    # drawing
    # ------------------------------------------------------------------
    def draw(self, surface, background):
        live = self.scrollbar.is_scrollable and self.scrollbar.in_motion
        # Re-bake when the mode flips, and also when a settled offset no
        # longer matches what the background holds — the offset can be moved
        # without a gesture (a reset, or a view rebuilding its rows), and the
        # separators would otherwise stay drawn where they used to be.
        stale = not live and self._baked_offset != self.scrollbar.offset
        if live != self._live_scroll or stale:
            self._live_scroll = live
            return self._switch_scroll_mode(surface, background)
        if live:
            return self._draw_scrollable(surface, background)
        return self._draw_settled(surface, background)

    def _switch_scroll_mode(self, surface, background):
        """Motion started or stopped: move the separators between the
        background and the per-frame path, then repaint once so the
        LayeredDirty bookkeeping matches the pixels again."""
        if background is not None:
            background.fill(self.background_color)
            self.draw_static_elements(background)
        self.full_paint(surface, background)
        return [surface.get_rect()]

    def _draw_settled(self, surface, background):
        """Ordinary dirty-rect draw. Clipped to the viewport when the list is
        scrollable, so rows scrolled above it cannot paint over the header."""
        self.ui_layer.clear(surface, background)
        rects = self.ui_layer.draw(surface)

        if self.scrollbar.is_scrollable:
            previous = surface.get_clip()
            surface.set_clip(self.scrollbar.viewport_rect())
            self.rows_layer.clear(surface, background)
            rects += self.rows_layer.draw(surface)
            surface.set_clip(previous)
        else:
            self.rows_layer.clear(surface, background)
            rects += self.rows_layer.draw(surface)
        return rects

    def _draw_scrollable(self, surface, background):
        """Immediate-mode redraw of the viewport, for frames where the offset
        is actually moving."""
        self.ui_layer.clear(surface, background)
        self.ui_layer.draw(surface)

        viewport = self.scrollbar.viewport_rect()
        previous = surface.get_clip()
        surface.set_clip(viewport)

        if background:
            surface.blit(background, viewport, viewport)
        for sprite in self.rows_layer.sprites():
            sprite.dirty = 1
        self.rows_layer.draw(surface)
        self.rows.draw_separators_live(surface, self.scrollbar.offset)

        surface.set_clip(previous)
        self.scrollbar.draw(surface)
        return [surface.get_rect()]

    def full_paint(self, surface, background):
        if background:
            self.draw_static_elements(background)
            surface.blit(background, (0, 0))

        for sprite in self.ui_layer.sprites():
            sprite.dirty = 1
        for sprite in self.rows_layer.sprites():
            sprite.dirty = 1

        self.ui_layer.clear(surface, background)
        self.ui_layer.draw(surface)

        if self.scrollbar.is_scrollable:
            # Same viewport clip as _draw_scrollable — a repaint while
            # scrolled (e.g. resuming from Wi-Fi setup) must not paint the
            # rows that sit above the viewport over the header.
            viewport = self.scrollbar.viewport_rect()
            previous = surface.get_clip()
            surface.set_clip(viewport)
            self.rows_layer.clear(surface, background)
            self.rows_layer.draw(surface)
            if self._live_scroll:
                self.rows.draw_separators_live(surface, self.scrollbar.offset)
            surface.set_clip(previous)
            self.scrollbar.draw(surface)
        else:
            self.rows_layer.clear(surface, background)
            self.rows_layer.draw(surface)
