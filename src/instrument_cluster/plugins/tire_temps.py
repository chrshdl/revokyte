"""Tire temperature quad — right column, top."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.skins import active_skin
from ..ui.utils import FontFamily
from ..ui.widgets.tire_temp_widget import TireTempWidget


class TireTempsPlugin(WidgetPlugin):
    plugin_id = "tire-temps"
    version = "1.0.0"

    def build_widgets(self):
        skin = active_skin()
        d = skin.dashboard
        grid = d.tire_grid
        sr = self.layout.shift_r
        ox, oy = grid.origin
        cw, ch = grid.cell
        cells = [
            (0, 0, "front_left", "T  FL"),
            (1, 0, "front_right", "T  FR"),
            (0, 1, "rear_left", "T  RL"),
            (1, 1, "rear_right", "T  RR"),
        ]
        return [
            TireTempWidget(
                rect=(
                    ox - sr + col * grid.col_step,
                    oy + row * grid.row_step,
                    cw,
                    ch,
                ),
                wheel_attr=attr,
                header_text=header,
                font_value_size=d.fonts.tire,
                font_value_family=FontFamily[d.fonts.tire_family],
                header_font_size=skin.style.header_font_size,
            )
            for col, row, attr, header in cells
        ]
