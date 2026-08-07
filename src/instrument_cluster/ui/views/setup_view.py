from importlib.metadata import PackageNotFoundError, version

from pygame.sprite import LayeredDirty

from ...addons.feeds import current_choice, feed_needs_reinstall, telemetry_choices
from ...config import ConfigManager
from ...extensions import runtime as extensions
from ...peripherals.display import is_raspberry_pi
from ...telemetry.mode import DiffReferenceMode, TelemetryMode
from ...ui.colors import Color
from ...ui.constants import (
    HEADER_BACKBUTTON_POSITION,
    HEADER_BACKBUTTON_SIZE,
    HEADER_LINE_TOPLEFT,
    HEADER_TITLE_FONT_SIZE,
    HEADER_TITLE_TOPLEFT,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from ...ui.events import (
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
    DIFF_REFERENCE_MODE_PRESSED,
    DIFF_REFERENCE_MODE_RELEASED,
    DIFF_REFERENCE_MODE_SELECTED,
    STATUS_LIGHTS_PRESSED,
    STATUS_LIGHTS_RELEASED,
    STATUS_LIGHTS_TOGGLED,
    TELEMETRY_MODE_PRESSED,
    TELEMETRY_MODE_RELEASED,
    TELEMETRY_MODE_SELECTED,
    WIFI_SETUP_PRESSED,
    WIFI_SETUP_RELEASED,
)
from ...ui.utils import FontFamily, load_font, spos, srect, su, sy
from ...ui.widgets.base.button import Button, ButtonEvents
from ...ui.widgets.base.dropdown import Dropdown
from ...ui.widgets.base.label import Label
from ...ui.widgets.base.line import Line
from ...ui.widgets.base.list_item import ListItem, ListItemGroup
from ...ui.widgets.base.scrollbar import Scrollbar
from ...ui.widgets.base.toggle import Toggle
from ...ui.widgets.settings.brightness_widget import BrightnessWidget
from .base import View


class SetupView(View):
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

        self._init_version_string()
        self._init_ui_elements()

        self._bind_dropdowns()

        self.background_color = Color.BLACK.rgb()

    def _init_version_string(self):
        try:
            self.app_version = version("instrument-cluster")
        except PackageNotFoundError:
            self.app_version = "dev"

    def _row_label(self, text: str) -> Label:
        """Standard row caption at row-local (LABEL_X, LABEL_DY)."""
        return Label(
            text=text,
            font=load_font(
                size=ListItem.ROW_FONT_SIZE, family=FontFamily.NOTOSANS_REGULAR
            ),
            color=Color.WHITE.rgb(),
            pos=spos(ListItem.LABEL_X, ListItem.LABEL_DY),
            center=False,
            bg_color=Color.BLACK.rgb(),
        )

    def _row_icon(self, glyph: str) -> Label:
        """Material-symbols row icon, centered in the icon cell at ICON_X."""
        return Label(
            text=glyph,
            font=load_font(size=ListItem.ICON_SIZE, family=FontFamily.MATERIAL_SYMBOLS),
            color=Color.WHITE.rgb(),
            pos=spos(ListItem.ICON_X, ListItem.DEFAULT_HEIGHT / 2 + 4),
            center=True,
            bg_color=Color.BLACK.rgb(),
            antialias=True,
        )

    def _row_button(self, text: str, icon: str, events: ButtonEvents) -> Button:
        """Standard row action button, styled like a closed dropdown header:
        same rect (DROPDOWN_X to the row's right edge, stretched to touch
        the separator lines), text on the VALUE_X column, the arrow icon in
        the chevron's spot, and the dropdown's pressed-grey glow instead of
        a border. Stops SEPARATOR_CLEARANCE short of the separator lines so
        the pressed fill never covers them."""
        width = SCREEN_WIDTH - ListItem.SEPARATOR_INSET - ListItem.DROPDOWN_X
        gap = ListItem.ROW_PITCH - ListItem.DEFAULT_HEIGHT
        clearance = ListItem.SEPARATOR_CLEARANCE
        return Button(
            rect=srect(
                ListItem.DROPDOWN_X,
                -gap / 2 + clearance,
                width,
                ListItem.DEFAULT_HEIGHT + gap - 2 * clearance,
            ),
            text=text,
            text_visible=True,
            font=load_font(
                size=ListItem.ROW_FONT_SIZE, family=FontFamily.NOTOSANS_REGULAR
            ),
            antialias=True,
            events=events,
            icon=icon,
            icon_size=46,
            icon_offset_y=su(4),
            icon_position="right",
            icon_fixed_right=True,
            text_color=Color.WHITE.rgb(),
            content_align="left",
            padding=(
                su(ListItem.VALUE_X - ListItem.DROPDOWN_X),
                su(20),
                su(20),
                su(20),
            ),
            text_offset_y=su(4),
            show_border=False,
            pressed_gradient=(Color.DARKER_GREY.rgb(), Color.DARKER_GREY.rgb()),
        )

    def _row_toggle(self, checked: bool, events: ButtonEvents) -> Toggle:
        """Standard row toggle switch, sharing the stretched rect of a
        closed dropdown header (whole control column as touch target, same
        pressed-grey glow, same SEPARATOR_CLEARANCE) with the switch pill
        right-aligned where the chevron sits."""
        width = SCREEN_WIDTH - ListItem.SEPARATOR_INSET - ListItem.DROPDOWN_X
        gap = ListItem.ROW_PITCH - ListItem.DEFAULT_HEIGHT
        clearance = ListItem.SEPARATOR_CLEARANCE
        return Toggle(
            rect=srect(
                ListItem.DROPDOWN_X,
                -gap / 2 + clearance,
                width,
                ListItem.DEFAULT_HEIGHT + gap - 2 * clearance,
            ),
            checked=checked,
            events=events,
        )

    def _row_dropdown(
        self, options, selected, events: ButtonEvents, labels=None
    ) -> Dropdown:
        """Standard row dropdown at row-local (DROPDOWN_X, 0), extending to
        the row's right edge (matching the separator lines) with no margin.
        Also stretched vertically to fill the row's grid cell (rather than
        leaving the row's natural top/bottom gap as black bands), stopping
        SEPARATOR_CLEARANCE short of the separator lines so the closed
        background and pressed fill never cover them — the open menu's
        option rows share this same sizing automatically, see
        Dropdown.get_option_rects()."""
        width = SCREEN_WIDTH - ListItem.SEPARATOR_INSET - ListItem.DROPDOWN_X
        gap = ListItem.ROW_PITCH - ListItem.DEFAULT_HEIGHT
        clearance = ListItem.SEPARATOR_CLEARANCE
        return Dropdown(
            rect=srect(
                ListItem.DROPDOWN_X,
                -gap / 2 + clearance,
                width,
                ListItem.DEFAULT_HEIGHT + gap - 2 * clearance,
            ),
            options=options,
            events=events,
            labels=labels,
            font=load_font(
                size=ListItem.ROW_FONT_SIZE, family=FontFamily.NOTOSANS_REGULAR
            ),
            selected_index=options.index(selected),
            menu_pitch=sy(ListItem.ROW_PITCH),
            text_left_pad=ListItem.VALUE_X - ListItem.DROPDOWN_X,
            menu_separator_color=ListItem.SEPARATOR_COLOR,
            menu_separator_width=ListItem.SEPARATOR_WIDTH,
        )

    def _init_ui_elements(self):
        self.title_label = Label(
            text="System settings",
            font=load_font(
                size=HEADER_TITLE_FONT_SIZE, family=FontFamily.NOTOSANS_LIGHT
            ),
            color=Color.WHITE.rgb(),
            pos=spos(*HEADER_TITLE_TOPLEFT),
            center=False,
        )
        self.back_button = Button(
            rect=srect(*HEADER_BACKBUTTON_POSITION, *HEADER_BACKBUTTON_SIZE),
            text="x",
            text_color=Color.WHITE.rgb(),
            text_visible=False,
            events=ButtonEvents(
                pressed=BUTTON_BACK_PRESSED,
                released=BUTTON_BACK_RELEASED,
            ),
            font=load_font(size=50, family=FontFamily.NOTOSANS_REGULAR),
            antialias=True,
            icon="",
            icon_color=Color.WHITE.rgb(),
            icon_size=54,
            icon_position="center",
        )
        self.horizontal_line = Line()

        config = ConfigManager.get_config()
        # Desktop builds have no proxy installer, so only feeds that can be
        # read in-process (plus Demo) are offered off the appliance.
        telemetry_options = telemetry_choices(direct_only=not is_raspberry_pi())
        self.telemetry_mode_dropdown = self._row_dropdown(
            options=telemetry_options,
            selected=current_choice(
                telemetry_options, config.telemetry_mode, config.telemetry_feed
            ),
            events=ButtonEvents(
                pressed=TELEMETRY_MODE_PRESSED,
                released=TELEMETRY_MODE_RELEASED,
                selected=TELEMETRY_MODE_SELECTED,
            ),
        )
        self.brightness_widget = BrightnessWidget(x=ListItem.VALUE_X)
        self.diff_reference_mode_dropdown = self._row_dropdown(
            options=self.DIFF_REFERENCE_OPTIONS,
            selected=DiffReferenceMode(config.diff_reference_mode),
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
            checked=config.status_lights,
            events=ButtonEvents(
                pressed=STATUS_LIGHTS_PRESSED,
                released=STATUS_LIGHTS_RELEASED,
                selected=STATUS_LIGHTS_TOGGLED,
            ),
        )

        # Custom dashboard slots are selected by swiping between pages on
        # the dashboard itself — there is no slot row in Setup.
        self.wifi_button = self._row_button(
            text="Wi-Fi Setup",
            icon="\ue5cc",
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
        # A feed left behind by an earlier image is flagged on the row that
        # re-installs it — picking the game again runs the install flow.
        stale = feed_needs_reinstall(
            config.telemetry_feed, config.telemetry_feed_version
        )
        telemetry_label = "Telemetry Mode"
        if config.telemetry_mode != TelemetryMode.DEMO.value and stale is not None:
            telemetry_label = "Telemetry (update)"
        row_contents = [("\ue51e", telemetry_label, self.telemetry_mode_dropdown)]
        if on_pi:
            row_contents.append(("\ue518", "Brightness", self.brightness_widget))
        row_contents += [
            ("\ue425", "Reference Lap", self.diff_reference_mode_dropdown),
            ("\ue0f0", "Status Lights", self.status_lights_toggle),
        ]
        if on_pi:
            row_contents.append(("\ue63e", "Network", self.wifi_button))
        for entry in extensions.setup_entries:
            text = (
                entry.button_text()
                if callable(entry.button_text)
                else entry.button_text
            )
            row_contents.append(
                (
                    entry.icon,
                    entry.label,
                    self._row_button(
                        text=text,
                        icon="\ue5cc",
                        events=ButtonEvents(
                            pressed=entry.pressed,
                            released=entry.released,
                        ),
                    ),
                )
            )
        self.rows = ListItemGroup(
            ListItem(
                y=ListItem.ROW_TOP + i * ListItem.ROW_PITCH,
                widgets=[self._row_icon(icon), self._row_label(text), control],
            )
            for i, (icon, text, control) in enumerate(row_contents)
        )

        self._dropdowns = [
            self.telemetry_mode_dropdown,
            self.diff_reference_mode_dropdown,
        ]

        self.scrollbar = Scrollbar(
            viewport_top=ListItem.ROW_TOP,
            viewport_height=SCREEN_HEIGHT - ListItem.ROW_TOP,
            content_height=self.rows.content_height,
            # Keep the track the same distance off the screen bottom as its
            # top sits below the header line.
            track_margin_bottom=ListItem.ROW_TOP - HEADER_LINE_TOPLEFT[1],
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

    def draw_static_elements(self, background_surface):
        """
        Draws non-moving elements (like lines) onto the background.
        """
        self.horizontal_line.draw(background_surface)
        if not self.scrollbar.is_scrollable:
            self.rows.draw_static_elements(background_surface)

    def draw(self, surface, background):
        if self.scrollbar.is_scrollable:
            return self._draw_scrollable(surface, background)

        self.ui_layer.clear(surface, background)
        self.rows_layer.clear(surface, background)
        return self.ui_layer.draw(surface) + self.rows_layer.draw(surface)

    def _draw_scrollable(self, surface, background):
        """Immediate-mode redraw of the scrollable viewport, every frame —
        row positions change continuously while dragging/bouncing, so the
        dirty-rect diff (which only repaints previously-dirty rects) can't
        keep up. The header stays on the normal dirty-rect path.
        """
        self.ui_layer.clear(surface, background)
        self.ui_layer.draw(surface)

        viewport = self.scrollbar.viewport_rect()
        prev_clip = surface.get_clip()
        surface.set_clip(viewport)

        if background:
            surface.blit(background, viewport, viewport)
        for sprite in self.rows_layer.sprites():
            sprite.dirty = 1
        self.rows_layer.draw(surface)
        self.rows.draw_separators_live(surface, self.scrollbar.offset)

        surface.set_clip(prev_clip)
        self.scrollbar.draw(surface)
        return [surface.get_rect()]

    def full_paint(self, surface, background):
        if background:
            self.draw_static_elements(background)
            surface.blit(background, (0, 0))

        for sprite in self.ui_layer.sprites():
            sprite.dirty = 1
        for sprite in self.rows_layer.sprites():
            sprite.dirty = 1

        self.ui_layer.clear(surface, background)
        self.ui_layer.draw(surface)

        if self.scrollbar.is_scrollable:
            # Same viewport clip as _draw_scrollable — a repaint while
            # scrolled (e.g. resuming from Wi-Fi setup) must not paint the
            # rows that sit above the viewport over the header.
            viewport = self.scrollbar.viewport_rect()
            prev_clip = surface.get_clip()
            surface.set_clip(viewport)
            self.rows_layer.clear(surface, background)
            self.rows_layer.draw(surface)
            self.rows.draw_separators_live(surface, self.scrollbar.offset)
            surface.set_clip(prev_clip)
            self.scrollbar.draw(surface)
        else:
            self.rows_layer.clear(surface, background)
            self.rows_layer.draw(surface)

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
