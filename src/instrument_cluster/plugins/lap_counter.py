"""Lap counter — right column, footer row."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.constants import LAP_WIDGET_HEIGHT, LAP_WIDGET_Y
from ..ui.utils import srect
from ..ui.widgets.lap_widget import LapWidget


class LapCounterPlugin(WidgetPlugin):
    plugin_id = "lap-counter"
    version = "1.0.0"

    def build_widgets(self):
        sr = self.layout.shift_r
        return [
            LapWidget(rect=srect(1172 - sr, LAP_WIDGET_Y, 90, LAP_WIDGET_HEIGHT))
        ]
