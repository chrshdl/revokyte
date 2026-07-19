from __future__ import annotations

from typing import Iterable

from pygame.sprite import LayeredDirty

from ...colors import Color
from ...constants import SCREEN_WIDTH
from ...utils import spos
from .container import Container
from .line import Line


class ListItem(Container):
    """A single settings row: takes a list of widgets and renders them.

    Child widgets are authored in row-local design coordinates (rects/positions
    relative to the row's top-left corner); the row scales its own (x, y) and
    shifts the children into place. Composite children (Containers) are
    supported and move as a unit.

    Rendering goes through the view's LayeredDirty group — call
    ``add_to_layered()`` once at construction. Events and updates are forwarded
    to every child via ``handle_event()`` / ``update()`` from Container.
    """

    # Row grid (design units): rows start below the header line and repeat at
    # a fixed pitch so overlays (e.g. open dropdown menus) can align with the
    # rows beneath them. A material-symbols icon sits in a fixed-width cell
    # centered on ICON_X, captions sit at LABEL_X, controls in a right-hand
    # column. Dropdown headers/menus and row action buttons start at
    # DROPDOWN_X, just left of their radio + value content at VALUE_X, and
    # extend to the separators' right edge (1240).
    # 5 uniform cells span the header line (y=100) to the screen bottom
    # (720): pitch = 620 / 5, and ROW_TOP leaves the stretch gap's upper
    # half above the first row so its cell starts at the header line.
    ROW_TOP = 122
    ROW_PITCH = 124
    ROW_FONT_SIZE = 32  # 34
    ICON_X = 84  # icon cell center
    ICON_SIZE = 34
    LABEL_X = 124
    LABEL_DY = 22  # 28
    VALUE_X = 685  # left edge of a row's value content (dropdown text, stepper)
    DROPDOWN_X = 658

    # Standard row content band (design px); matches the button/dropdown
    # height rows are authored against (see BrightnessWidget).
    DEFAULT_HEIGHT = 80
    SEPARATOR_COLOR = Color.MID_GREY.rgb()
    SEPARATOR_WIDTH = 1
    SEPARATOR_INSET = 40
    # Stretched row controls (dropdown headers, action buttons) stop this
    # far short of the separator lines so their background/pressed fill
    # never paints over them.
    SEPARATOR_CLEARANCE = 2

    def __init__(
        self,
        y: float,
        widgets: Iterable[object],
        x: float = 0,
        height: float = DEFAULT_HEIGHT,
        show_separator: bool = True,
    ):
        px, py = spos(x, y)
        super().__init__(x=px, y=py)
        self.add(*widgets)

        # Design-space (unscaled) position/height, kept around so separators
        # between rows can be placed without re-deriving them from scaled
        # sprite rects.
        self._design_x = x
        self._design_y = y
        self.height = height
        self.show_separator = show_separator

    @property
    def design_bottom(self) -> float:
        """Row-content bottom edge, in design (unscaled) coordinates."""
        return self._design_y + self.height

    def scroll_to(self, offset: float) -> None:
        """Reposition this row by a vertical scroll offset (design px)."""
        x, y = spos(self._design_x, self._design_y - offset)
        self.set_pos(x, y)

    @classmethod
    def draw_separators(
        cls, rows: Iterable["ListItem"], surface, offset: float = 0.0
    ) -> None:
        """Draw a thin line centered in the gap between each consecutive
        pair of rows. Skips a gap when either row opts out via
        ``show_separator=False``. ``offset`` (design px) shifts the
        separators to track a live scroll position; the default of 0 is for
        a view's ``draw_static_elements()``, where separators are baked
        once into the non-moving background.
        """
        rows = list(rows)
        for prev, nxt in zip(rows, rows[1:]):
            if not (prev.show_separator and nxt.show_separator):
                continue
            y = (prev.design_bottom + nxt._design_y) / 2 - offset
            Line(
                start_pos=(cls.SEPARATOR_INSET, y),
                length=SCREEN_WIDTH - 2 * cls.SEPARATOR_INSET,
                color=cls.SEPARATOR_COLOR,
                width=cls.SEPARATOR_WIDTH,
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
        """Scrollable span in design (unscaled) px: from the first row's
        content top to the last row's grid-cell bottom. A row's cell extends
        half the inter-row gap beyond its content band, and stretched row
        controls (dropdown headers, action buttons, toggles) fill that cell —
        stopping at the content band would leave them clipped by the screen
        edge at max scroll."""
        if not self.rows:
            return 0.0
        last = self.rows[-1]
        bottom_half_gap = (ListItem.ROW_PITCH - last.height) / 2
        return last.design_bottom + bottom_half_gap - self.rows[0]._design_y

    def add_to_layered(self, layered: LayeredDirty) -> None:
        for row in self.rows:
            row.add_to_layered(layered)

    def handle_event(self, event) -> None:
        for row in self.rows:
            row.handle_event(event)

    def scroll_to(self, offset: float) -> None:
        """Shift every row by a vertical scroll offset (design px) and mark
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
