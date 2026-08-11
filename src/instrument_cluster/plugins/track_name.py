"""Track name — left column, above the footer (from TrackSignal)."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.skins import active_skin
from ..ui.utils import FontFamily
from ..ui.widgets.track_name_widget import TrackNameWidget


class TrackNamePlugin(WidgetPlugin):
    plugin_id = "track-name"
    version = "1.0.0"

    def build_widgets(self):
        skin = active_skin()
        d = skin.dashboard
        x, y, w, h = d.track_rect
        return [
            TrackNameWidget(
                rect=(x + self.layout.shift_l, y, w, h),
                font_value_size=d.fonts.track,
                font_value_family=FontFamily[d.fonts.track_family],
                header_font_size=skin.style.header_font_size,
            )
        ]
