"""Predicted lap time — left column, second slot."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.skins import active_skin
from ..ui.utils import FontFamily
from ..ui.widgets.predicted_lap_time_widget import PredictedLapTimeWidget


class PredictedLapPlugin(WidgetPlugin):
    plugin_id = "predicted-lap"
    version = "1.0.0"

    def build_widgets(self):
        skin = active_skin()
        d = skin.dashboard
        x, y, w, h = d.predicted_lap_rect
        return [
            PredictedLapTimeWidget(
                rect=(x + self.layout.shift_l, y, w, h),
                font_value_size=d.fonts.predicted_lap,
                font_value_family=FontFamily[d.fonts.predicted_lap_family],
                header_font_size=skin.style.header_font_size,
            )
        ]
