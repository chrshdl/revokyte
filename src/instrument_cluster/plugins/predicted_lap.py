"""Predicted lap time — left column, second slot."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.utils import srect
from ..ui.widgets.predicted_lap_time_widget import PredictedLapTimeWidget


class PredictedLapPlugin(WidgetPlugin):
    plugin_id = "predicted-lap"
    version = "1.0.0"

    def build_widgets(self):
        sl = self.layout.shift_l
        return [PredictedLapTimeWidget(rect=srect(186 + sl, 163, 352, 94))]
