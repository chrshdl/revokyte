"""Previous lap time — right column."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.utils import srect
from ..ui.widgets.lap_time_widget import LapTimeWidget


class LapTimePlugin(WidgetPlugin):
    plugin_id = "lap-time"
    version = "1.0.0"

    def build_widgets(self):
        sr = self.layout.shift_r
        return [LapTimeWidget(rect=srect(1094 - sr, 454, 336, 100))]
