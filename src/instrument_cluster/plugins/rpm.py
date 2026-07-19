"""RPM bar — center dial, under the speed readout."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..peripherals.display import DESIGN_WIDTH
from ..ui.utils import srect
from ..ui.widgets.rpm_widget import RpmWidget


class RpmPlugin(WidgetPlugin):
    plugin_id = "rpm"
    version = "1.0.0"

    def build_widgets(self):
        cx = DESIGN_WIDTH // 2
        return [RpmWidget(rect=srect(cx, 186, 196, 74))]
