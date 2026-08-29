"""RPM bar — center dial, under the speed readout."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.skins import active_skin
from ..ui.utils import FontFamily
from ..ui.widgets.ferrari_rpm_widget import FerrariRpmWidget
from ..ui.widgets.rpm_widget import RpmWidget


class RpmPlugin(WidgetPlugin):
    plugin_id = "rpm"
    version = "1.1.0"

    def build_widgets(self):
        skin = active_skin()
        d = skin.dashboard
        # Which gauge this panel wears is a skin decision (dashboard.rpm_variant),
        # not a plugin one: the Ferrari bar is authored against the 1280 grid and
        # the smaller panels have not had their pass, so they keep the classic
        # needle gauge rather than a squeezed version of the segmented bar.
        if d.rpm_variant == "ferrari":
            return [
                FerrariRpmWidget(
                    rect=d.rpm_rect,
                    rpm_style=skin.style.rpm,
                    label_font_size=d.fonts.rpm_label,
                    label_font_family=FontFamily[d.fonts.rpm_label_family],
                    header_font_size=skin.style.header_font_size,
                )
            ]
        return [
            RpmWidget(
                rect=d.rpm_rect,
                rpm_style=skin.style.rpm,
                label_font_size=d.fonts.rpm_label,
                label_font_family=FontFamily[d.fonts.rpm_label_family],
                header_font_size=skin.style.header_font_size,
            )
        ]
