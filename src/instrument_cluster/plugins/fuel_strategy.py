"""Fuel strategy pair — fuel per lap + laps remaining.

Splits the third left-column slot (186, 258, 352, 94) into two
side-by-side boxes with a 4-design-px gap. Free like every standard
gauge; a current-lap-time block remains available in the custom
dashboard builder for layouts that prefer it.
"""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.utils import srect
from ..ui.widgets.fuel_laps_widget import FuelLapsWidget
from ..ui.widgets.fuel_per_lap_widget import FuelPerLapWidget


class FuelStrategyPlugin(WidgetPlugin):
    plugin_id = "fuel-strategy"
    version = "1.1.0"

    def build_widgets(self):
        sl = self.layout.shift_l
        return [
            FuelPerLapWidget(rect=srect(97 + sl, 258, 175, 94)),
            FuelLapsWidget(rect=srect(274 + sl, 258, 175, 94)),
        ]
