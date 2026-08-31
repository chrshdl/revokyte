"""The Testing & Validation screen: a standing-start acceleration timer.

Opened from Setup. Two settings rows on the familiar grid — the distance to
run to, and a Reset — and under them the one thing the driver actually looks
at: the clock, as large as the space below the rows allows.

The screen is read from a moving car, so it says its state in words rather
than expecting the driver to infer it from a number that is or isn't moving:
the status line under the clock is always the answer to "what is it waiting
for?".

Geometry comes from the active skin's ``setup`` group (the row grid, shared
with Setup and Software) plus the space that block leaves over — this screen
adds no skin fields of its own, so it lands correctly on a panel whose skin
nobody has tuned for it.
"""

from __future__ import annotations

from pygame.sprite import LayeredDirty

from ...config import ConfigManager
from ...core.vehicle.accel_timer import DISTANCES_M
from ...ui.colors import Color
from ...ui.events import (
    ACCEL_DISTANCE_PRESSED,
    ACCEL_DISTANCE_RELEASED,
    ACCEL_DISTANCE_SELECTED,
    ACCEL_RESET_PRESSED,
    ACCEL_RESET_RELEASED,
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
)
from ...ui.icons import Icon
from ...ui.skins import active_skin
from ...ui.utils import FontFamily, load_font_px
from ...ui.widgets.base.button import ButtonEvents
from ...ui.widgets.base.digit_readout import DigitReadout
from ...ui.widgets.base.dropdown import Dropdown
from ...ui.widgets.base.label import Label
from ...ui.widgets.base.list_item import ListItem, ListItemGroup
from .base import View
from .header import corner_button, header_line, header_title
from .setup_rows import row_button, row_dropdown, row_icon, row_label


def _centered(text: str, size: int, family: FontFamily, color, pos) -> Label:
    """A readout line centered on ``pos``, at an exact pixel size."""
    return Label(
        text=text,
        font=load_font_px(size, family),
        color=color,
        pos=pos,
        center=True,
        antialias=True,
    )


class AccelTestView(View):
    DISTANCE_OPTIONS = list(DISTANCES_M)

    def __init__(self):
        # One LayeredDirty for the whole screen, unlike Setup's two. The
        # clock sits *under* the open distance menu, and only a single group
        # z-orders them: the menu's opaque scrim would otherwise be painted
        # once and then written over by the next tick of a clock in another
        # group, since a group only repaints its own dirty sprites.
        self.ui_layer = LayeredDirty()
        self.ui_layer._use_update = True

        self._init_ui_elements()
        self.distance_dropdown.bind_group(
            self.ui_layer,
            menu_layer=Dropdown.DROPDOWN_MENU_LAYER,
            open_header_layer=Dropdown.DROPDOWN_HEADER_OPEN_LAYER,
        )

        self.background_color = Color.BLACK.rgb()

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _init_ui_elements(self):
        skin = active_skin()
        s = skin.setup

        self.title_label = header_title("Testing & Validation")
        self.back_button = corner_button(
            icon=Icon.BACK.glyph(),
            events=ButtonEvents(
                pressed=BUTTON_BACK_PRESSED,
                released=BUTTON_BACK_RELEASED,
            ),
        )
        self.horizontal_line = header_line()

        # Nothing here reads /data: the selection is bound by reset(), which
        # runs before the screen is ever shown (see the View contract).
        self.distance_dropdown = row_dropdown(
            options=self.DISTANCE_OPTIONS,
            selected=self.DISTANCE_OPTIONS[-1],
            labels={m: f"{m} m" for m in self.DISTANCE_OPTIONS},
            events=ButtonEvents(
                pressed=ACCEL_DISTANCE_PRESSED,
                released=ACCEL_DISTANCE_RELEASED,
                selected=ACCEL_DISTANCE_SELECTED,
            ),
        )
        self.reset_button = row_button(
            text="Reset",
            icon=Icon.RESET_TIMER.glyph(),
            events=ButtonEvents(
                pressed=ACCEL_RESET_PRESSED,
                released=ACCEL_RESET_RELEASED,
            ),
        )

        row_contents = [
            (Icon.DISTANCE.glyph(), "Distance", self.distance_dropdown),
            (Icon.TIMER.glyph(), "Timer", self.reset_button),
        ]
        self.rows = ListItemGroup(
            ListItem(
                y=s.row_top + i * s.row_pitch,
                widgets=[row_icon(icon), row_label(text), control],
            )
            for i, (icon, text, control) in enumerate(row_contents)
        )
        self.rows.add_to_layered(self.ui_layer)

        # Everything below the two rows belongs to the readout. Sized off
        # that free height so the clock is as big as each panel allows: 157
        # px tall on the 1280x720, 105 on the 800x480.
        rows_bottom = s.row_top + len(row_contents) * s.row_pitch
        free_h = skin.height - rows_bottom

        # The gauges' fixed digit grid, for the same reason they have it: the
        # hundredths change 100 times a second, and a clock that re-centres
        # itself on every reading cannot be read at a glance. "00.00" fixes
        # the field width, so passing 10 s does not shove the digits sideways
        # either — and "sec" then keeps its place beside them.
        clock_size = int(free_h * 0.45)
        self.time_label = DigitReadout(
            pos=(skin.width // 2, rows_bottom + int(free_h * 0.42)),
            font=load_font_px(clock_size, FontFamily.D_DIN_EXP_BOLD),
            color=Color.WHITE.rgb(),
            template="00.00",
            unit="sec",
            unit_font=load_font_px(int(clock_size * 0.32), FontFamily.D_DIN_EXP),
            unit_color=Color.WHITE.rgb(),
            digit_gap=skin.style.digit_gap,
            unit_gap=int(clock_size * 0.16),
        )
        self.status_label = _centered(
            "",
            size=s.row_font_size,
            family=FontFamily.D_DIN_EXP,
            color=Color.LIGHT_GREY.rgb(),
            pos=(skin.width // 2, rows_bottom + int(free_h * 0.80)),
        )

        self.ui_layer.add(
            self.title_label, self.back_button, self.time_label, self.status_label
        )

    # ------------------------------------------------------------------
    # binding
    # ------------------------------------------------------------------
    def reset(self, ctx=None) -> None:
        """A freshly-opened screen: the stored distance, a zeroed clock, no
        menu left open and no button left pressed by the tap that got here."""
        self.close_dropdowns()
        self.release_presses(self.ui_layer)

        target = ConfigManager.get_config().accel_test_distance
        if target in self.DISTANCE_OPTIONS:
            self.distance_dropdown.set_selected_index(
                self.DISTANCE_OPTIONS.index(target)
            )

        self.set_readout(0.0)
        self.set_status("")

    def set_readout(self, seconds: float) -> None:
        """The clock, in seconds to hundredths — the resolution the
        measurement actually supports (see accel_timer's docstring)."""
        self.time_label.set_text(f"{max(0.0, seconds):.2f}")

    @property
    def time_text(self) -> str:
        return self.time_label.text

    def set_status(self, text: str, color: tuple[int, int, int] | None = None) -> None:
        self.status_label.set_color(Color.LIGHT_GREY.rgb() if color is None else color)
        self.status_label.set_text(text)

    def close_dropdowns(self) -> None:
        self.distance_dropdown._set_open(False)

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------
    def draw_static_elements(self, background_surface) -> None:
        self.horizontal_line.draw(background_surface)
        self.rows.draw_static_elements(background_surface)

    def update(self, dt: float):
        self.ui_layer.update(dt)

    def draw(self, surface, background):
        self.ui_layer.clear(surface, background)
        return self.ui_layer.draw(surface)

    def full_paint(self, surface, background):
        if background:
            self.draw_static_elements(background)
            surface.blit(background, (0, 0))

        for sprite in self.ui_layer.sprites():
            sprite.dirty = 1

        self.ui_layer.clear(surface, background)
        self.ui_layer.draw(surface)

    def handle_event(self, event) -> bool:
        if Dropdown.handle_priority_event(event, [self.distance_dropdown]):
            return True

        self.back_button.handle_event(event)
        self.rows.handle_event(event)
        return False
