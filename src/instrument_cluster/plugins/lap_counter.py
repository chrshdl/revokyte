"""Lap counter — right column, footer row."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.colors import Color
from ..ui.skins import active_skin
from ..ui.utils import FontFamily
from ..ui.widgets.lap_widget import LapWidget


class LapCounterPlugin(WidgetPlugin):
    plugin_id = "lap-counter"
    version = "1.0.0"

    def build_widgets(self):
        skin = active_skin()
        d = skin.dashboard
        x, y, w, h = d.lap_counter_rect
        return [
            LapWidget(
                rect=(x - self.layout.shift_r, y, w, h),
                font_value_size=d.fonts.lap_counter,
                font_value_family=FontFamily[d.fonts.lap_counter_family],
                value_color=Color[d.lap_counter_color].rgb(),
                header_font_size=skin.style.header_font_size,
            )
        ]
