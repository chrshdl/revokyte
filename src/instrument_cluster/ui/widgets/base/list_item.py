from __future__ import annotations

from typing import Iterable

from pygame.sprite import LayeredDirty

from ...colors import Color
from ...skins import active_skin
from .container import Container
from .line import Line


class ListItem(Container):
    """A single settings row: takes a list of widgets and renders them.

    Child widgets are authored in row-local coordinates (rects/positions
    relative to the row's top-left corner, native px); the row shifts the
    children into place. Composite children (Containers) are supported and
    move as a unit.

    The row grid — where rows start, how far apart they repeat, where the
    icon/label/control columns sit — comes from the active skin's ``setup``
    group (``active_skin().setup``), read at construction time so overlays
    (e.g. open dropdown menus) can align with the rows beneath them. Each
    skin picks its own row count: the 1280x720 layout fits 5 uniform cells
    between the header line and the screen bottom.

    Rendering goes through the view's LayeredDirty group — call
    ``add_to_layered()`` once at construction. Events and updates are
    forwarded to every child via ``handle_event()`` / ``update()`` from
    Container.
    """

    @classmethod
    def separator_color(cls) -> tuple:
        # Resolved per call so palette overrides (skin editor) reach a
        # rebuilt list.
        return Color.MID_GREY.rgb()

    def __init__(
        self,
        y: float,
        widgets: Iterable[object],
        x: float = 0,
        height: float | None = None,
        show_separator: bool = True,
    ):
        super().__init__(x=round(x), y=round(y))
        self.add(*widgets)

        # Native (unscrolled) position/height, kept around so separators
        # between rows can be placed without re-deriving them from scrolled
        # sprite rects.
        self._base_x = x
        self._base_y = y
        self.height = (
            active_skin().setup.row_height if height is None else height
        )
        self.show_separator = show_separator

    @property
    def base_bottom(self) -> float:
        """Row-content bottom edge, in unscrolled native coordinates."""
        return self._base_y + self.height

    def scroll_to(self, offset: float) -> None:
        """Reposition this row by a vertical scroll offset (native px)."""
        self.set_pos(round(self._base_x), round(self._base_y - offset))

    @classmethod
    def draw_separators(
        cls, rows: Iterable["ListItem"], surface, offset: float = 0.0
    ) -> None:
        """Draw a thin line centered in the gap between each consecutive
        pair of rows. Skips a gap when either row opts out via
        ``show_separator=False``. ``offset`` (native px) shifts the
        separators to track a live scroll position; the default of 0 is for
        a view's ``draw_static_elements()``, where separators are baked
        once into the non-moving background.
        """
        skin = active_skin()
        inset = skin.setup.separator_inset
        rows = list(rows)
        for prev, nxt in zip(rows, rows[1:]):
            if not (prev.show_separator and nxt.show_separator):
                continue
            y = (prev.base_bottom + nxt._base_y) / 2 - offset
            Line(
                start_pos=(inset, y),
                length=skin.width - 2 * inset,
                color=cls.separator_color(),
                width=skin.setup.separator_width,
            ).draw(surface)


class ListItemGroup:
    """An ordered sequence of ListItem rows rendered as a settings list.

    Bundles the per-row sprite wiring, event dispatch, and inter-row
    separator drawing so a view just forwards its own calls without knowing
    how rows relate to each other.
    """

    def __init__(self, rows: Iterable[ListItem]):
        self.rows = list(rows)

    def __iter__(self):
        return iter(self.rows)

    @property
    def content_height(self) -> float:
        """Scrollable span in native px: from the first row's content top
        to the last row's grid-cell bottom. A row's cell extends half the
        inter-row gap beyond its content band, and stretched row controls
        (dropdown headers, action buttons, toggles) fill that cell —
        stopping at the content band would leave them clipped by the screen
        edge at max scroll."""
        if not self.rows:
            return 0.0
        last = self.rows[-1]
        pitch = active_skin().setup.row_pitch
        bottom_half_gap = (pitch - last.height) / 2
        return last.base_bottom + bottom_half_gap - self.rows[0]._base_y

    def add_to_layered(self, layered: LayeredDirty) -> None:
        for row in self.rows:
            row.add_to_layered(layered)

    def handle_event(self, event) -> None:
        for row in self.rows:
            row.handle_event(event)

    def scroll_to(self, offset: float) -> None:
        """Shift every row by a vertical scroll offset (native px) and mark
        their sprites dirty so the dirty-rect renderer repaints them."""
        for row in self.rows:
            row.scroll_to(offset)
            for sprite in row.sprites():
                sprite.dirty = 1

    def draw_static_elements(self, surface) -> None:
        """Draw the non-moving separators between rows onto the background."""
        ListItem.draw_separators(self.rows, surface)

    def draw_separators_live(self, surface, offset: float) -> None:
        """Like ``draw_static_elements``, but positioned for a live scroll
        offset. For use in the scrollable draw path, which redraws the
        viewport every frame instead of baking separators into the
        background (they need to move with the rows)."""
        ListItem.draw_separators(self.rows, surface, offset=offset)
