"""Speed readout — center dial, top."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..peripherals.display import DESIGN_WIDTH
from ..ui.utils import srect
from ..ui.widgets.speed_widget import SpeedWidget


class SpeedPlugin(WidgetPlugin):
    plugin_id = "speed"
    version = "1.0.0"

    def build_widgets(self):
        cx = DESIGN_WIDTH // 2
        return [SpeedWidget(rect=srect(cx, 92, 220, 140))]
