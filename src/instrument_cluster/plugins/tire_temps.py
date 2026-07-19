"""Tire temperature quad — right column, top."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.utils import srect
from ..ui.widgets.tire_temp_widget import TireTempWidget


class TireTempsPlugin(WidgetPlugin):
    plugin_id = "tire-temps"
    version = "1.0.0"

    def build_widgets(self):
        sr = self.layout.shift_r
        return [
            TireTempWidget(
                rect=srect(1014 - sr, 22, 122, 92),
                wheel_attr="front_left",
                header_text="T  FL",
            ),
            TireTempWidget(
                rect=srect(1140 - sr, 22, 122, 92),
                wheel_attr="front_right",
                header_text="T  FR",
            ),
            TireTempWidget(
                rect=srect(1014 - sr, 118, 122, 92),
                wheel_attr="rear_left",
                header_text="T  RL",
            ),
            TireTempWidget(
                rect=srect(1140 - sr, 118, 122, 92),
                wheel_attr="rear_right",
                header_text="T  RR",
            ),
        ]
