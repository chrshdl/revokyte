"""Delta time to the reference lap — right column.

Twice the fuel-box height (2 × 94), top edge aligned with the fuel pair
across the dial (y 211): spans 211..399, mirroring the left column's
rhythm between the tire temps (…210) and lap time (404…).
"""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.utils import srect
from ..ui.widgets.delta_time_widget import DeltaTimeWidget


class DeltaPlugin(WidgetPlugin):
    plugin_id = "delta"
    version = "1.0.0"

    def build_widgets(self):
        sr = self.layout.shift_r
        return [DeltaTimeWidget(rect=srect(1094 - sr, 308, 336, 150))]
