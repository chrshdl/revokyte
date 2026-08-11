"""Previous lap time — right column."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.skins import active_skin
from ..ui.utils import FontFamily
from ..ui.widgets.lap_time_widget import LapTimeWidget


class LapTimePlugin(WidgetPlugin):
    plugin_id = "lap-time"
    version = "1.0.0"

    def build_widgets(self):
        skin = active_skin()
        d = skin.dashboard
        x, y, w, h = d.lap_time_rect
        return [
            LapTimeWidget(
                rect=(x - self.layout.shift_r, y, w, h),
                font_value_size=d.fonts.lap_time,
                font_value_family=FontFamily[d.fonts.lap_time_family],
                header_font_size=skin.style.header_font_size,
            )
        ]
