"""Speed readout — center dial, top."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.colors import Color
from ..ui.skins import active_skin
from ..ui.utils import FontFamily
from ..ui.widgets.speed_widget import SpeedWidget


class SpeedPlugin(WidgetPlugin):
    plugin_id = "speed"
    version = "1.0.0"

    def build_widgets(self):
        skin = active_skin()
        d = skin.dashboard
        return [
            SpeedWidget(
                rect=d.speed_rect,
                font_value_size=d.fonts.speed,
                font_value_family=FontFamily[d.fonts.speed_family],
                value_color=Color[d.speed_color].rgb(),
                header_font_size=skin.style.header_font_size,
            )
        ]
