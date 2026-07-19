"""Gear indicator — center dial."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..peripherals.display import DESIGN_WIDTH
from ..ui.utils import srect
from ..ui.widgets.gear_widget import GearWidget


class GearPlugin(WidgetPlugin):
    plugin_id = "gear"
    version = "1.0.0"

    def build_widgets(self):
        cx = DESIGN_WIDTH // 2
        return [GearWidget(rect=srect(cx, 388, 186, 232))]
