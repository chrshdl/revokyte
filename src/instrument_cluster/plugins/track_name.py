"""Track name — left column, above the footer (from TrackSignal)."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.utils import srect
from ..ui.widgets.track_name_widget import TrackNameWidget


class TrackNamePlugin(WidgetPlugin):
    plugin_id = "track-name"
    version = "1.0.0"

    def build_widgets(self):
        sl = self.layout.shift_l
        return [TrackNameWidget(rect=srect(186 + sl, 454, 352, 94))]
