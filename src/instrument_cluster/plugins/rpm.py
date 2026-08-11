"""RPM bar — center dial, under the speed readout."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.skins import active_skin
from ..ui.utils import FontFamily
from ..ui.widgets.rpm_widget import RpmWidget


class RpmPlugin(WidgetPlugin):
    plugin_id = "rpm"
    version = "1.0.0"

    def build_widgets(self):
        skin = active_skin()
        d = skin.dashboard
        return [
            RpmWidget(
                rect=d.rpm_rect,
                rpm_style=skin.style.rpm,
                label_font_size=d.fonts.rpm_label,
                label_font_family=FontFamily[d.fonts.rpm_label_family],
                header_font_size=skin.style.header_font_size,
            )
        ]
