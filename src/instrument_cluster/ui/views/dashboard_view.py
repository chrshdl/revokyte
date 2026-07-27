import pygame
from pygame.sprite import LayeredDirty

from ...config import ConfigManager
from ...core.plugin_system.plugin_layout import STATUS_STRIP_W, LayoutContext
from ...peripherals.display import DESIGN_WIDTH
from ...ui.colors import Color
from ...ui.constants import (
    BUTTON_HEIGHT,
    FOOTER_BUTTONGROUP_Y,
)
from ...ui.events import (
    BUTTON_SETUP_LONGPRESSED,
    BUTTON_SETUP_PRESSED,
    BUTTON_SETUP_RELEASED,
)
from ...ui.utils import FontFamily, load_font, srect, su
from ...ui.widgets.base.button import Button, ButtonEvents
from ...ui.widgets.slot_dots_widget import SlotDotsWidget
from ...ui.widgets.slot_name_widget import SlotNameWidget
from ...ui.widgets.status_lights_widget import StatusLightsWidget
from .base import View

class DashboardView(View):
    """The dashboard's chrome and compositor.

    The telemetry gauges themselves are plugins (see ``core/sdk.py`` and
    ``src/instrument_cluster/plugins/``); their sprites are linked into
    ``plugin_layer`` by ``DashboardState``. The view owns only the system
    chrome: the Setup button (``ui_layer``) and the optional bezel LED
    strips (``widget_layer``).

    Draw order: widget_layer (chrome) → plugin_layer (gauges) → ui_layer
    (Setup button on top). ``plugin_layer`` is drawn and
    cleared here but never group-updated — plugins pump their own widgets'
    ``update(bus, dt)`` from the main loop, which avoids the signature
    clash with ``ui_layer.update(dt)``.
    """

    # Kept as a class attribute for layout tests; the value now lives in
    # core/plugin_layout.py so gauge plugins shift by the same amount.
    _STATUS_STRIP_W = STATUS_STRIP_W

    def __init__(self):
        self.ui_layer = LayeredDirty()
        self.widget_layer = LayeredDirty()
        # Gauge plugins render here, between the chrome layers.
        self.plugin_layer = LayeredDirty()

        self.status_lights_enabled = ConfigManager.get_config().status_lights
        self._apply_shifts()

        # (count, active) of the slot page indicator; kept here so a chrome
        # rebuild (status-lights toggle) restores the dots' state.
        self._slot_pages = (1, 0)
        # Active slot name, kept for the same reason: the label is rebuilt
        # with the footer (it anchors to the shifting track column).
        self._slot_name = ""

        self._init_ui_elements()
        self._init_widgets()

        # Slot page indicator (default + synced custom slots); hidden while
        # only one page exists. Lives in ui_layer — drawn last, so it
        # overlays custom-layout gauges and survives the plugin layer's
        # first-draw background blit. Created once: it is layout-independent
        # and must not duplicate on the status-lights chrome rebuild.
        self.slot_dots = SlotDotsWidget()
        self.slot_dots.set_state(*self._slot_pages)
        self.ui_layer.add(self.slot_dots)

        self.background_color = Color.BLACK.rgb()

    def _apply_shifts(self):
        # The bezel status LEDs are optional (Setup toggle). With them off
        # no strip is reserved and both widget columns return to the
        # strip-less layout (shifts 0, i.e. margins of 10 design-px on the
        # left and 18 on the right). Gauge plugins derive their shifts from
        # the same LayoutContext (see DashboardState.on_resume).
        layout = LayoutContext(status_lights=self.status_lights_enabled)
        self._SHIFT_L = layout.shift_l
        self._SHIFT_R = layout.shift_r

        # Design-space rect of the Track widget (a plugin, but the footer
        # buttons still align to its left edge).
        self._TRACK_RECT = (186 + self._SHIFT_L, 454, 352, 94)
        # Left edge of the track widget; the footer buttons align to it.
        self._COLUMN_LEFT = self._TRACK_RECT[0] - self._TRACK_RECT[2] // 2

    def set_status_lights(self, enabled: bool) -> None:
        """Reflow the chrome for the status-lights toggle without discarding
        the view — plugin sprites in plugin_layer/ui_layer are preserved
        (gauge plugins reflow themselves via PluginManager.relayout)."""
        if enabled == self.status_lights_enabled:
            return
        self.status_lights_enabled = enabled
        self._apply_shifts()

        # widget_layer holds only view-owned sprites → safe to rebuild.
        self.widget_layer.empty()
        # setup_button + slot_name share ui_layer with external plugin
        # sprites; drop just them (not the whole layer) and let
        # _init_ui_elements re-add fresh ones at the new column position.
        self.ui_layer.remove(self.setup_button)
        self.ui_layer.remove(self.slot_name)

        self._init_ui_elements()  # rebuilds setup_button + slot_name (+re-adds)
        self._init_widgets()  # rebuilds the chrome incl. the LED strips

    def _init_ui_elements(self):
        self.setup_button = Button(
            rect=srect(self._COLUMN_LEFT, FOOTER_BUTTONGROUP_Y, 110, BUTTON_HEIGHT),
            text="Setup",
            text_color=Color.WHITE.rgb(),
            text_gap=0,
            text_visible=True,
            text_position="top",
            events=ButtonEvents(
                pressed=BUTTON_SETUP_PRESSED,
                released=BUTTON_SETUP_RELEASED,
                long_pressed=BUTTON_SETUP_LONGPRESSED,
            ),
            font=load_font(size=32, family=FontFamily.PIXEL_TYPE),
            antialias=True,
            icon="\ue8b8",
            icon_color=Color.WHITE.rgb(),
            icon_size=34,
            icon_position="center",
            icon_gap=0,
            content_align="center",
            padding=(0, su(8), 0, 0),
            icon_cell_width=su(34),
        )
        self.ui_layer.add(self.setup_button)

        # Slot name label: fills the footer from just right of the Setup
        # button to the track column's right edge (its right edge == the
        # Track widget's right edge).
        track_right = self._COLUMN_LEFT + self._TRACK_RECT[2]
        name_left = self._COLUMN_LEFT + 120
        self.slot_name = SlotNameWidget(
            rect=(
                name_left,
                FOOTER_BUTTONGROUP_Y,
                track_right - name_left,
                BUTTON_HEIGHT,
            )
        )
        self.slot_name.set_value(self._slot_name)
        self.ui_layer.add(self.slot_name)

    def _init_widgets(self):
        # Bezel status LEDs at the screen edges (amber TC / blue ASM),
        # unless disabled in Setup.
        if self.status_lights_enabled:
            strip_w = self._STATUS_STRIP_W
            self.widget_layer.add(
                StatusLightsWidget(rect=srect(0, 54, strip_w, 224)),
                StatusLightsWidget(
                    rect=srect(DESIGN_WIDTH - strip_w, 54, strip_w, 224)
                ),
            )

    def set_slot_pages(self, count: int, active: int) -> None:
        """Reflect the available dashboard pages in the dot indicator."""
        self._slot_pages = (count, active)
        self.slot_dots.set_state(count, active)

    def set_slot_name(self, name: str) -> None:
        """Show the active slot's name in the footer label (empty hides it)."""
        self._slot_name = name
        self.slot_name.set_value(name)

    def update(self, bus, dt: float):
        self.ui_layer.update(dt)

        # plugin_layer is intentionally NOT updated here — gauge plugins
        # drive their widgets from PluginManager.update() in the main loop.
        self.widget_layer.update(bus, dt)

    def draw(self, surface, background):
        self.widget_layer.clear(surface, background)
        self.plugin_layer.clear(surface, background)
        self.ui_layer.clear(surface, background)
        return (
            self.widget_layer.draw(surface)
            + self.plugin_layer.draw(surface)
            + self.ui_layer.draw(surface)
        )

    def full_paint(self, surface, background):
        for layer in (self.widget_layer, self.plugin_layer, self.ui_layer):
            for sprite in layer.sprites():
                sprite.dirty = 1

        if background:
            surface.blit(background, (0, 0))

        for layer in (self.widget_layer, self.plugin_layer, self.ui_layer):
            layer.clear(surface, background)
            layer.draw(surface)

    def handle_event(self, event):
        self.setup_button.handle_event(event)
