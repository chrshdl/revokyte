"""Delta time to the reference lap — right column.

Sits between the tire quad and the previous-lap block; each skin keeps
the column rhythm at its own resolution.
"""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.skins import active_skin
from ..ui.utils import FontFamily
from ..ui.widgets.delta_time_widget import DeltaTimeWidget


class DeltaPlugin(WidgetPlugin):
    plugin_id = "delta"
    version = "1.0.0"

    def build_widgets(self):
        skin = active_skin()
        d = skin.dashboard
        x, y, w, h = d.delta_rect
        return [
            DeltaTimeWidget(
                rect=(x - self.layout.shift_r, y, w, h),
                font_value_size=d.fonts.delta,
                font_value_family=FontFamily[d.fonts.delta_family],
                delta_style=skin.style.delta,
                state_font_size=d.fonts.delta_state,
                state_font_family=FontFamily[d.fonts.delta_state_family],
                header_font_size=skin.style.header_font_size,
            )
        ]
