"""Fastest lap time — left column, top."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.colors import Color
from ..ui.skins import active_skin
from ..ui.utils import FontFamily
from ..ui.widgets.fastest_lap_time_widget import FastestLapTimeWidget


class FastestLapPlugin(WidgetPlugin):
    plugin_id = "fastest-lap"
    version = "1.0.0"

    def build_widgets(self):
        skin = active_skin()
        d = skin.dashboard
        x, y, w, h = d.fastest_lap_rect
        return [
            FastestLapTimeWidget(
                rect=(x + self.layout.shift_l, y, w, h),
                font_value_size=d.fonts.fastest_lap,
                font_value_family=FontFamily[d.fonts.fastest_lap_family],
                value_color=Color[d.fastest_lap_color].rgb(),
                header_font_size=skin.style.header_font_size,
            )
        ]
