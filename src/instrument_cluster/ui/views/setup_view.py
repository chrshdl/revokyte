from pygame.sprite import LayeredDirty

from ...addons.feeds import current_choice, feed_needs_reinstall, telemetry_choices
from ...config import ConfigManager
from ...extensions import runtime as extensions
from ...peripherals.display import is_raspberry_pi
from ...telemetry.mode import DiffReferenceMode, TelemetryMode
from ...ui.colors import Color
from ...ui.events import (
    ACCEL_TEST_PRESSED,
    ACCEL_TEST_RELEASED,
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
    DIFF_REFERENCE_MODE_PRESSED,
    DIFF_REFERENCE_MODE_RELEASED,
    DIFF_REFERENCE_MODE_SELECTED,
    SHIFT_LIGHTS_PRESSED,
    SHIFT_LIGHTS_RELEASED,
    SHIFT_LIGHTS_TOGGLED,
    SOFTWARE_PRESSED,
    SOFTWARE_RELEASED,
    STATUS_LIGHTS_PRESSED,
    STATUS_LIGHTS_RELEASED,
    STATUS_LIGHTS_TOGGLED,
    TELEMETRY_MODE_PRESSED,
    TELEMETRY_MODE_RELEASED,
    TELEMETRY_MODE_SELECTED,
    WIFI_SETUP_PRESSED,
    WIFI_SETUP_RELEASED,
)
from ...ui.icons import Icon
from ...ui.skins import active_skin
from ...ui.widgets.base.button import ButtonEvents
from ...ui.widgets.base.dropdown import Dropdown
from ...ui.widgets.base.list_item import ListItem, ListItemGroup
from ...ui.widgets.base.scrollbar import Scrollbar
from ...ui.widgets.base.toggle import Toggle
from ...ui.widgets.settings.brightness_widget import BrightnessWidget
from .base import View
from .header import corner_button, header_line, header_title
from .scrollable_rows import ScrollableRowsView
from .setup_rows import (
    row_button,
    row_control_rect,
    row_dropdown,
    row_icon,
    row_label,
)


def _entry_text(entry) -> str:
    """An extension row's label. Callable button_text is re-evaluated on every
    entry to the screen, which is the whole point of allowing a callable."""
    return entry.button_text() if callable(entry.button_text) else entry.button_text


def _entry_text_static(entry) -> str:
    """The part of an extension row's label that construction may safely read.

    A callable button_text can reach anything the extension likes — Pro's
    reads licence state off /data — so it is not evaluated while building.
    reset() fills it in before the row is ever shown.
    """
    return "" if callable(entry.button_text) else entry.button_text


class SetupView(ScrollableRowsView, View):
    STEP_PERCENT = 10
    DIFF_REFERENCE_OPTIONS = [DiffReferenceMode.PREVIOUS, DiffReferenceMode.FASTEST]

    def __init__(self):
        # ui_layer: header chrome (title, back button) — plain dirty-rect.
        # rows_layer: the settings rows — scrolls, and switches to an
        # immediate-mode redraw of its own viewport once content overflows.
        #
        # Two groups share one destination surface, so both must skip
        # LayeredDirty's "first draw" full-screen mode (_use_update starts
        # False): on an untimed first call it blits its own background over
        # the *entire* surface before drawing its sprites, which would wipe
        # out whatever the other group just painted. Forcing dirty-rect mode
        # from the start keeps each group's draw scoped to its own sprites'
        # rects.
        self.ui_layer = LayeredDirty()
        self.ui_layer._use_update = True
        self.rows_layer = LayeredDirty()
        self.rows_layer._use_update = True

        self._init_ui_elements()

        self._bind_dropdowns()

        self.background_color = Color.BLACK.rgb()

    def _row_toggle(self, checked: bool, events: ButtonEvents) -> Toggle:
        """Standard row toggle switch, sharing the stretched rect of a
        closed dropdown header (whole control column as touch target, same
        pressed-grey glow, same separator_clearance) with the switch pill
        right-aligned where the chevron sits."""
        return Toggle(rect=row_control_rect(), checked=checked, events=events)

    def _init_ui_elements(self):
        self.title_label = header_title("System settings")
        self.back_button = corner_button(
            icon=Icon.BACK.glyph(),
            events=ButtonEvents(
                pressed=BUTTON_BACK_PRESSED,
                released=BUTTON_BACK_RELEASED,
            ),
        )
        self.horizontal_line = header_line()

        # Nothing here may read /data. The row *set* comes from the image
        # (which feeds exist, whether this is a Pi, which extensions are
        # installed); every value shown in it is bound by reset() before the
        # screen is displayed. That split is what lets a build() failure mean
        # "this image is defective" — see core/system/unhealthy.py.
        #
        # Desktop builds have no proxy installer, so only feeds that can be
        # read in-process (plus Demo) are offered off the appliance.
        telemetry_options = telemetry_choices(direct_only=not is_raspberry_pi())
        self.telemetry_mode_dropdown = row_dropdown(
            options=telemetry_options,
            selected=telemetry_options[0],
            events=ButtonEvents(
                pressed=TELEMETRY_MODE_PRESSED,
                released=TELEMETRY_MODE_RELEASED,
                selected=TELEMETRY_MODE_SELECTED,
            ),
        )
        self.brightness_widget = BrightnessWidget(x=active_skin().setup.value_x)
        self.diff_reference_mode_dropdown = row_dropdown(
            options=self.DIFF_REFERENCE_OPTIONS,
            selected=self.DIFF_REFERENCE_OPTIONS[0],
            # Without these the row would read a bare, lowercase "fastest" —
            # the raw config value. Same source as the gauge header.
            labels={mode: mode.label for mode in self.DIFF_REFERENCE_OPTIONS},
            events=ButtonEvents(
                pressed=DIFF_REFERENCE_MODE_PRESSED,
                released=DIFF_REFERENCE_MODE_RELEASED,
                selected=DIFF_REFERENCE_MODE_SELECTED,
            ),
        )
        self.status_lights_toggle = self._row_toggle(
            checked=False,
            events=ButtonEvents(
                pressed=STATUS_LIGHTS_PRESSED,
                released=STATUS_LIGHTS_RELEASED,
                selected=STATUS_LIGHTS_TOGGLED,
            ),
        )
        self.shift_lights_toggle = self._row_toggle(
            checked=False,
            events=ButtonEvents(
                pressed=SHIFT_LIGHTS_PRESSED,
                released=SHIFT_LIGHTS_RELEASED,
                selected=SHIFT_LIGHTS_TOGGLED,
            ),
        )

        # Custom dashboard slots are selected by swiping between pages on
        # the dashboard itself — there is no slot row in Setup.
        self.wifi_button = row_button(
            text="Wi-Fi Setup",
            icon=Icon.CHEVRON_RIGHT.glyph(),
            events=ButtonEvents(
                pressed=WIFI_SETUP_PRESSED,
                released=WIFI_SETUP_RELEASED,
            ),
        )
        # One ListItem per grid slot, top to bottom. Extensions may
        # contribute extra rows; with none installed the list below
        # is all there is. Brightness (panel backlight) and Network
        # (appliance Wi-Fi setup) only exist on the Pi \u2014 in a desktop
        # window the OS owns both; the widgets above are still built so
        # SetupState can address them unconditionally.
        on_pi = is_raspberry_pi()
        self._telemetry_caption = row_label(self._DEFAULT_TELEMETRY_LABEL)
        row_contents = [
            (
                Icon.TELEMETRY_MODE.glyph(),
                self._telemetry_caption,
                self.telemetry_mode_dropdown,
            )
        ]
        if on_pi:
            row_contents.append(
                (Icon.BRIGHTNESS.glyph(), "Brightness", self.brightness_widget)
            )
        row_contents += [
            (
                Icon.REFERENCE_LAP.glyph(),
                "Reference Lap",
                self.diff_reference_mode_dropdown,
            ),
            (Icon.STATUS_LIGHTS.glyph(), "Status Lights", self.status_lights_toggle),
            (Icon.SHIFT_LIGHTS.glyph(), "Shift Lights", self.shift_lights_toggle),
        ]
        if on_pi:
            row_contents.append((Icon.NETWORK.glyph(), "Network", self.wifi_button))
        # Versions, factory reset, and extension update flows live on
        # the Software screen — one row here instead of several.
        self.software_button = row_button(
            text="Version",
            icon=Icon.CHEVRON_RIGHT.glyph(),
            events=ButtonEvents(
                pressed=SOFTWARE_PRESSED,
                released=SOFTWARE_RELEASED,
            ),
        )
        row_contents.append((Icon.SOFTWARE.glyph(), "Software", self.software_button))
        # The acceleration timer: a driving measurement, not a setting, so
        # it gets its own screen rather than a control in this list.
        self.testing_button = row_button(
            text="Acceleration",
            icon=Icon.CHEVRON_RIGHT.glyph(),
            events=ButtonEvents(
                pressed=ACCEL_TEST_PRESSED,
                released=ACCEL_TEST_RELEASED,
            ),
        )
        row_contents.append(
            (Icon.TESTING.glyph(), "Testing & Validation", self.testing_button)
        )
        # Held as (entry, button) pairs: button_text may be a callable that is
        # re-evaluated on every entry to Setup (an extension's licence row
        # reads its tier that way), and a pooled view would otherwise show
        # whatever it said at boot forever.
        self._extension_rows = []
        for entry in extensions.setup_entries:
            button = row_button(
                text=_entry_text_static(entry),
                icon=Icon.CHEVRON_RIGHT.glyph(),
                events=ButtonEvents(
                    pressed=entry.pressed,
                    released=entry.released,
                ),
            )
            self._extension_rows.append((entry, button))
            row_contents.append((entry.icon, entry.label, button))
        s = active_skin().setup
        self.rows = ListItemGroup(
            ListItem(
                y=s.row_top + i * s.row_pitch,
                widgets=[
                    row_icon(icon),
                    text if not isinstance(text, str) else row_label(text),
                    control,
                ],
            )
            for i, (icon, text, control) in enumerate(row_contents)
        )

        self._dropdowns = [
            self.telemetry_mode_dropdown,
            self.diff_reference_mode_dropdown,
        ]

        skin = active_skin()
        self.scrollbar = Scrollbar(
            viewport_top=s.row_top,
            viewport_height=skin.height - s.row_top,
            content_height=self.rows.content_height,
            # Keep the track the same distance off the screen bottom as its
            # top sits below the header line.
            track_margin_bottom=s.row_top - skin.header.line_y,
            # Come to rest on whole rows — never leave one half-cut under
            # the header.
            snap_interval=s.row_pitch,
        )

        self.ui_layer.add(self.title_label, self.back_button)
        self.rows.add_to_layered(self.rows_layer)

    def _bind_dropdowns(self):
        """
        Bind dropdown menus to the rendering layer.
        """
        for dropdown in self._dropdowns:
            dropdown.bind_group(
                self.rows_layer,
                menu_layer=Dropdown.DROPDOWN_MENU_LAYER,
                open_header_layer=Dropdown.DROPDOWN_HEADER_OPEN_LAYER,
            )

    # ------------------------------------------------------------------
    # per-entry rebinding
    # ------------------------------------------------------------------
    _DEFAULT_TELEMETRY_LABEL = "Telemetry Mode"

    @staticmethod
    def _telemetry_label_text(config) -> str:
        # A feed left behind by an earlier image is flagged on the row that
        # re-installs it — picking the game again runs the install flow.
        stale = feed_needs_reinstall(
            config.telemetry_feed, config.telemetry_feed_version
        )
        if config.telemetry_mode != TelemetryMode.DEMO.value and stale is not None:
            return "Telemetry (update)"
        return SetupView._DEFAULT_TELEMETRY_LABEL

    def reset(self, ctx=None) -> None:
        """Make this view indistinguishable from a freshly built one.

        Everything here is state the *previous* visit left behind, or config
        that changed while Setup was closed — the install flow writes the
        telemetry mode and feed, and an extension's row label tracks live
        state. A pooled view shows all of it stale otherwise.
        """
        config = ConfigManager.get_config()

        self.close_dropdowns()
        self.release_presses(self.ui_layer, self.rows_layer)
        self.scrollbar.reset()
        self.rows.scroll_to(0.0, force=True)

        self._telemetry_caption.set_text(self._telemetry_label_text(config))

        options = self.telemetry_mode_dropdown.options
        selection = current_choice(
            options, config.telemetry_mode, config.telemetry_feed
        )
        if selection in options:
            self.telemetry_mode_dropdown.set_selected_index(options.index(selection))

        diff_mode = DiffReferenceMode(config.diff_reference_mode)
        if diff_mode in self.DIFF_REFERENCE_OPTIONS:
            self.diff_reference_mode_dropdown.set_selected_index(
                self.DIFF_REFERENCE_OPTIONS.index(diff_mode)
            )

        self.status_lights_toggle.set_checked(config.status_lights)
        self.shift_lights_toggle.set_checked(config.shift_lights)
        self.set_brightness_text(config.brightness)

        for entry, button in self._extension_rows:
            button.set_text(_entry_text(entry))

    def set_brightness_text(self, value):
        self.brightness_widget.set_percent(value)

    def close_dropdowns(self):
        for dropdown in self._dropdowns:
            dropdown._set_open(False)

    def update(self, dt: float):
        self.ui_layer.update(dt)
        self.rows_layer.update(dt)

        if self.scrollbar.is_scrollable:
            self.scrollbar.update(dt)
            self.rows.scroll_to(self.scrollbar.offset)

    def handle_event(self, event) -> bool:
        """
        Delegates events to widgets.
        Returns True if a widget consumed the event.
        """
        if Dropdown.handle_priority_event(event, self._dropdowns):
            return True

        if self.scrollbar.handle_event(event, self.rows):
            return False

        self.back_button.handle_event(event)
        self.rows.handle_event(event)

        return False
