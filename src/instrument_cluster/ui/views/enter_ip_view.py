from collections.abc import Iterable

from pygame.sprite import LayeredDirty

from ...config import ConfigManager
from ...ip4 import get_ip_prefill
from ...ui.colors import Color
from ...ui.constants import (
    BUTTON_DIMENSIONS,
    BUTTON_GRID_OFFSET,
    BUTTONS_PER_ROW,
    HEADER_BACKBUTTON_POSITION,
    HEADER_BACKBUTTON_SIZE,
    HEADER_TITLE_FONT_SIZE,
    HEADER_TITLE_TOPLEFT,
    NUMPAD_OFFSET,
    RECENT_BUTTONS_DIMENSIONS,
    RECENT_BUTTONS_GRID_OFFSET,
    RECENT_BUTTONS_OFFSET,
    RECENT_BUTTONS_PER_ROW,
    RECENT_CONNECTIONS_POSITION,
)
from ...ui.events import (
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
    ENTER_IP_DEL_BUTTON_PRESSED,
    ENTER_IP_DEL_BUTTON_RELEASED,
    ENTER_IP_KEYPAD_BUTTON_PRESSED,
    ENTER_IP_KEYPAD_BUTTON_RELEASED,
    ENTER_IP_OK_BUTTON_PRESSED,
    ENTER_IP_OK_BUTTON_RELEASED,
)
from ...ui.utils import FontFamily, load_font, spos, srect, sx, sy
from ...ui.widgets.base.button import Button, ButtonEvents, ButtonGroup
from ...ui.widgets.base.label import Label
from ...ui.widgets.base.line import Line
from ...ui.widgets.base.textfield import TextField
from .base import View


class EnterIPView(View):
    def __init__(
        self, recent_connected: list[str] | None = None, title: str | None = None
    ):
        self.ui_layer = LayeredDirty()
        self.button_group = ButtonGroup()

        self.background_color = Color.BLACK.rgb()

        self._title = title or "Enter Playstation IP"
        self._init_ui_elements(recent_connected or [])

    def _init_ui_elements(self, recent_connected):
        # 1. Static Elements
        self.title_label = Label(
            text=self._title,
            font=load_font(
                size=HEADER_TITLE_FONT_SIZE, family=FontFamily.NOTOSANS_LIGHT
            ),
            color=Color.WHITE.rgb(),
            pos=spos(*HEADER_TITLE_TOPLEFT),
            center=False,
        )
        self.horizontal_line = Line()

        self.recent_label = Label(
            text="Recent connections",
            font=load_font(size=46, family=FontFamily.PIXEL_TYPE),
            color=Color.WHITE.rgb(),
            pos=spos(*RECENT_CONNECTIONS_POSITION),
            center=True,
            antialias=False,
            visible=len(ConfigManager.get_config().recent_connected) > 0,
        )

        # 2. Input Field
        self.textfield = TextField(
            text=get_ip_prefill(),
            font=load_font(size=36, family=FontFamily.NOTOSANS_REGULAR),
            color=Color.WHITE.rgb(),
            pos=spos(62, 142),
            width=sx(356),
            height=sy(76),
        )

        # 3. Buttons
        self.back_button = Button(
            rect=srect(*HEADER_BACKBUTTON_POSITION, *HEADER_BACKBUTTON_SIZE),
            text="x",
            text_visible=False,
            events=ButtonEvents(
                pressed=BUTTON_BACK_PRESSED,
                released=BUTTON_BACK_RELEASED,
            ),
            font=load_font(size=50, family=FontFamily.PIXEL_TYPE),
            antialias=True,
            icon="\ue5cd",
            icon_color=Color.WHITE.rgb(),
            icon_size=48,
            icon_position="center",
        )

        self.del_button = Button(
            rect=srect(416, 142, 110, 76),
            text="<",
            text_visible=False,
            events=ButtonEvents(
                pressed=ENTER_IP_DEL_BUTTON_PRESSED,
                released=ENTER_IP_DEL_BUTTON_RELEASED,
            ),
            font=load_font(size=36, family=FontFamily.PIXEL_TYPE),
            text_color=Color.LIGHT_RED.rgb(),
            antialias=True,
            icon="\ue14a",
            icon_size=46,
            icon_position="center",
            pressed_gradient=(Color.RPM_DARK_RED.rgb(), Color.BLACK.rgb()),
            border_top_right_radius=4,
            border_bottom_right_radius=4,
        )

        self.ok_button = Button(
            rect=srect(424, 398, 100, 164),
            text="OK",
            text_visible=False,
            events=ButtonEvents(
                pressed=ENTER_IP_OK_BUTTON_PRESSED,
                released=ENTER_IP_OK_BUTTON_RELEASED,
            ),
            font=load_font(size=50, family=FontFamily.PIXEL_TYPE),
            text_color=Color.GREEN.rgb(),
            antialias=True,
            icon="\ue5ca",
            icon_size=46,
            icon_position="center",
            pressed_gradient=(Color.DARK_GREEN.rgb(), Color.BLACK.rgb()),
        )

        # 4. Generate Grids
        labels = list("123456789#0.")
        self.button_group.extend_buttons(
            self._button_grid_generator(
                labels,
                BUTTONS_PER_ROW,
                BUTTON_GRID_OFFSET,
                NUMPAD_OFFSET,
                BUTTON_DIMENSIONS,
            )
        )
        self.button_group.extend_buttons(
            self._button_grid_generator(
                recent_connected[0:3],
                RECENT_BUTTONS_PER_ROW,
                RECENT_BUTTONS_GRID_OFFSET,
                RECENT_BUTTONS_OFFSET,
                RECENT_BUTTONS_DIMENSIONS,
            )
        )
        self.button_group.add(self.back_button, self.del_button, self.ok_button)

        # 5. Add everything to UI Layer
        self.ui_layer.add(
            self.title_label,
            self.recent_label,
            self.textfield,
            *self.button_group.sprites(),
        )

    def _button_grid_generator(
        self,
        labels: Iterable[str],
        buttons_per_row: int,
        grid_offset: tuple[int, int],
        global_offset: tuple[int, int],
        button_size: tuple[int, int],
    ) -> list[Button]:
        return [
            Button(
                rect=srect(
                    i % buttons_per_row * grid_offset[0] + global_offset[0],
                    i // buttons_per_row * grid_offset[1] + global_offset[1],
                    button_size[0],
                    button_size[1],
                ),
                text=val,
                icon=None,
                events=ButtonEvents(
                    pressed=ENTER_IP_KEYPAD_BUTTON_PRESSED,
                    released=ENTER_IP_KEYPAD_BUTTON_RELEASED,
                ),
                event_data={"label": val},
                font=load_font(size=34, family=FontFamily.NOTOSANS_REGULAR),
                antialias=True,
            )
            for i, val in enumerate(labels or [])
        ]

    # --- Draw / Update Hooks ---

    def draw_static_elements(self, background_surface):
        self.horizontal_line.draw(background_surface)

    def update(self, dt):
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

    def handle_event(self, event):
        self.button_group.handle_event(event)
        self.textfield.handle_event(event)
        return False
