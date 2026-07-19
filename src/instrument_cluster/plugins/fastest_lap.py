"""Fastest lap time — left column, top."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.utils import srect
from ..ui.widgets.fastest_lap_time_widget import FastestLapTimeWidget


class FastestLapPlugin(WidgetPlugin):
    plugin_id = "fastest-lap"
    version = "1.0.0"

    def build_widgets(self):
        sl = self.layout.shift_l
        return [FastestLapTimeWidget(rect=srect(186 + sl, 68, 352, 94))]
