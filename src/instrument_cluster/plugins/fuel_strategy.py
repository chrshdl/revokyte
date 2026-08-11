"""Fuel strategy pair — fuel per lap + laps remaining.

Two side-by-side boxes splitting the third left-column slot. Free like
every standard gauge; a current-lap-time block remains available in the
custom dashboard builder for layouts that prefer it.
"""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.colors import Color
from ..ui.skins import active_skin
from ..ui.utils import FontFamily
from ..ui.widgets.fuel_laps_widget import FuelLapsWidget
from ..ui.widgets.fuel_per_lap_widget import FuelPerLapWidget


class FuelStrategyPlugin(WidgetPlugin):
    plugin_id = "fuel-strategy"
    version = "1.1.0"

    def build_widgets(self):
        skin = active_skin()
        d = skin.dashboard
        sl = self.layout.shift_l
        px, py, pw, ph = d.fuel_per_lap_rect
        lx, ly, lw, lh = d.fuel_laps_rect
        common = dict(
            font_value_size=d.fonts.fuel,
            font_value_family=FontFamily[d.fonts.fuel_family],
            header_font_size=skin.style.header_font_size,
        )
        return [
            FuelPerLapWidget(
                rect=(px + sl, py, pw, ph),
                value_color=Color[d.fuel_per_lap_color].rgb(),
                **common,
            ),
            FuelLapsWidget(
                rect=(lx + sl, ly, lw, lh),
                value_color=Color[d.fuel_laps_color].rgb(),
                **common,
            ),
        ]
