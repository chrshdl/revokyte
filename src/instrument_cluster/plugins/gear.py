"""Gear indicator — center dial."""

from ..core.plugin_system.sdk import WidgetPlugin
from ..ui.colors import Color
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
                header_text=d.gear_header_text,
                font_value_size=d.fonts.gear,
                font_value_family=FontFamily[d.fonts.gear_family],
                value_color=Color[d.gear_color].rgb(),
                header_font_size=skin.style.header_font_size,
                # Panel styling is per-skin: the 296 GT3 wears a light panel
                # with a dark numeral and a grey border, the default panels a
                # flat black one with none. Equal gradient ends are a flat
                # fill, and width 0 turns the border off.
                text_color=Color[d.gear_header_color].rgb(),
                bg_gradient_top=Color[d.gear_gradient_top].rgb(),
                bg_gradient_bottom=Color[d.gear_gradient_bottom].rgb(),
                border_color=Color[d.gear_border_color].rgb(),
                border_width=d.gear_border_width,
                border_radius=d.gear_border_radius,
                shadow_depth_pct=d.gear_shadow_depth_pct,
                shadow_color=Color[d.gear_shadow_color].rgb(),
                bevel_light=Color[d.gear_bevel_light].rgb(),
                bevel_dark=Color[d.gear_bevel_dark].rgb(),
                bevel_width=d.gear_bevel_width,
                show_border=d.gear_border_width > 0,
            )
        ]
