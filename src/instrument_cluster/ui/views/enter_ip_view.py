from collections.abc import Iterable

from pygame.sprite import LayeredDirty

from ...config import ConfigManager
from ...ip4 import get_ip_prefill
from ...ui.colors import Color
from ...ui.icons import Icon
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
from ...ui.skins import active_skin
from ...ui.utils import FontFamily, load_font_px
from ...ui.widgets.base.button import Button, ButtonEvents, ButtonGroup
from ...ui.widgets.base.label import Label
from ...ui.widgets.base.textfield import TextField
from .base import View
from .header import corner_button, header_line, header_title


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
        skin = active_skin()
        np = skin.numpad

        # 1. Static Elements
        self.title_label = header_title(self._title)
        self.horizontal_line = header_line()

        self.recent_label = Label(
            text="Recent connections",
            font=load_font_px(
                np.recent_label_font,
                FontFamily[np.recent_label_font_family],
            ),
            color=Color.WHITE.rgb(),
            pos=np.recent_position,
            center=True,
            antialias=False,
            visible=len(ConfigManager.get_config().recent_connected) > 0,
        )

        # 2. Input Field
        fx, fy, fw, fh = np.field_rect
        self.textfield = TextField(
            text=get_ip_prefill(),
            font=load_font_px(np.field_font, FontFamily[np.field_font_family]),
            color=Color.WHITE.rgb(),
            pos=(fx, fy),
            width=fw,
            height=fh,
        )

        # 3. Buttons
        self.back_button = corner_button(
            icon=Icon.CLOSE.glyph(),
            events=ButtonEvents(
                pressed=BUTTON_BACK_PRESSED,
                released=BUTTON_BACK_RELEASED,
            ),
        )

        self.del_button = Button(
            rect=np.del_rect,
            text="<",
            text_visible=False,
            events=ButtonEvents(
                pressed=ENTER_IP_DEL_BUTTON_PRESSED,
                released=ENTER_IP_DEL_BUTTON_RELEASED,
            ),
            font=load_font_px(np.field_font, FontFamily.PIXEL_TYPE),
            text_color=Color.LIGHT_RED.rgb(),
            antialias=True,
            icon=Icon.BACKSPACE.glyph(),
            icon_size=46,
            icon_position="center",
            pressed_gradient=(Color.RPM_DARK_RED.rgb(), Color.BLACK.rgb()),
            border_top_right_radius=4,
            border_bottom_right_radius=4,
        )

        self.ok_button = Button(
            rect=np.ok_rect,
            text="OK",
            text_visible=False,
            events=ButtonEvents(
                pressed=ENTER_IP_OK_BUTTON_PRESSED,
                released=ENTER_IP_OK_BUTTON_RELEASED,
            ),
            font=load_font_px(skin.header.title_font_size, FontFamily.PIXEL_TYPE),
            text_color=Color.GREEN.rgb(),
            antialias=True,
            icon=Icon.OK_CHECK.glyph(),
            icon_size=46,
            icon_position="center",
            pressed_gradient=(Color.DARK_GREEN.rgb(), Color.BLACK.rgb()),
        )

        # 4. Generate Grids
        labels = list("123456789#0.")
        self.button_group.extend_buttons(
            self._button_grid_generator(
                labels,
                np.buttons_per_row,
                (
                    np.button_dims[0] + np.button_margin,
                    np.button_dims[1] + np.button_margin,
                ),
                np.offset,
                np.button_dims,
            )
        )
        self.button_group.extend_buttons(
            self._button_grid_generator(
                recent_connected[0:3],
                np.recent_per_row,
                (
                    np.recent_dims[0] + np.recent_margin,
                    np.recent_dims[1] + np.recent_margin,
                ),
                np.recent_offset,
                np.recent_dims,
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
        np = active_skin().numpad
        key_font = load_font_px(np.key_font, FontFamily[np.key_font_family])
        return [
            Button(
                rect=(
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
                font=key_font,
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
