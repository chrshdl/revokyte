"""Gear indicator — center dial."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.skins import active_skin
from ..ui.utils import FontFamily
from ..ui.widgets.gear_widget import GearWidget


class GearPlugin(WidgetPlugin):
    plugin_id = "gear"
    version = "1.0.0"

    def build_widgets(self):
        skin = active_skin()
        d = skin.dashboard
        return [
            GearWidget(
                rect=d.gear_rect,
                font_value_size=d.fonts.gear,
                font_value_family=FontFamily[d.fonts.gear_family],
                header_font_size=skin.style.header_font_size,
            )
        ]
