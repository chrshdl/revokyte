"""The Software screen: version inventory, factory reset, extension rows.

Opened from Setup's "Software" row. Versions live here and only here —
one row per installed component — so neither Setup nor an extension's
update flow needs to repeat them. Below the inventory: the factory-reset
row (appliance only), then action rows contributed by extensions (e.g.
the Pro update flow).
"""

from importlib.metadata import PackageNotFoundError, version

from pygame.sprite import LayeredDirty

from ...extensions import runtime as extensions
from ...peripherals.display import is_raspberry_pi
from ...ui.colors import Color
from ...ui.events import (
    BUTTON_BACK_PRESSED,
    BUTTON_BACK_RELEASED,
    FACTORY_RESET_PRESSED,
    FACTORY_RESET_RELEASED,
)
from ...ui.icons import Icon
from ...ui.skins import active_skin
from ...ui.widgets.base.button import ButtonEvents
from ...ui.widgets.base.list_item import ListItem, ListItemGroup
from ...ui.widgets.base.scrollbar import Scrollbar
from .base import View
from .scrollable_rows import ScrollableRowsView
from .header import corner_button, header_line, header_title
from .setup_rows import row_button, row_icon, row_label, row_value

_OS_RELEASE_PATH = "/etc/os-release"
_IMAGE_OS_ID = "instrument-cluster"


def _read_os_release(path: str = _OS_RELEASE_PATH) -> dict[str, str]:
    info: dict[str, str] = {}
    try:
        with open(path, "r") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    info[k] = v.strip('"')
    except OSError:
        return {}
    return info


def image_version(path: str = _OS_RELEASE_PATH) -> str | None:
    """Release version of the appliance OS image, or None when the app is
    not running on it. Keyed on the image's os-release ID rather than on
    the platform: desktop Linux and stock Raspberry Pi OS carry their own
    /etc/os-release, whose VERSION_ID is the distro's release — showing
    that as the cluster's version would be wrong exactly where support
    needs the number. VERSION_ID is the OS release tag (CI-tagged builds
    only); local image builds fall back to their BUILD_ID timestamp.
    """
    info = _read_os_release(path)
    if info.get("ID") != _IMAGE_OS_ID:
        return None
    return info.get("VERSION_ID") or info.get("BUILD_ID") or None


def app_version() -> str:
    """The installed app version, without the PEP-440 local segment
    (+g<hash>.d<date> on dev builds via setuptools_scm) — release tags
    carry none, and the full string overflows the row's value column."""
    try:
        full = version("instrument-cluster")
    except PackageNotFoundError:
        return "dev"
    return full.split("+", 1)[0]


def component_versions(path: str = _OS_RELEASE_PATH) -> list[tuple[str, str]]:
    """The device's software inventory: the release-relevant numbers only.

    App always; OS (the image release tag — TF-11's Soll-Release check
    reads this row) only on the appliance image, keyed on the os-release
    ID. Internals like the delta calculator or the Buildroot toolchain
    series are deliberately not listed — support gets them from the
    release tag. Extension-contributed entries (e.g. the Pro package)
    come last; a callable version is re-evaluated per view build.
    """
    rows = [("App", app_version())]
    info = _read_os_release(path)
    if info.get("ID") == _IMAGE_OS_ID:
        rows.append(("OS", info.get("VERSION_ID") or info.get("BUILD_ID") or "—"))
    for name, ver in extensions.version_entries:
        rows.append((name, ver() if callable(ver) else ver))
    return rows


def _entry_text(entry) -> str:
    """An extension row's label, re-evaluated per entry when it is callable
    (the Pro update row reads "Check for updates" vs a pending version)."""
    return entry.button_text() if callable(entry.button_text) else entry.button_text


def _entry_text_static(entry) -> str:
    """The part of the label construction may safely read: a callable can
    reach /data (Pro's licence row does), so reset() evaluates it instead."""
    return "" if callable(entry.button_text) else entry.button_text


class SoftwareView(ScrollableRowsView, View):
    _FACTORY_RESET_IDLE_TEXT = "Factory Reset"
    _FACTORY_RESET_ARMED_TEXT = "Tap again to reset"

    def __init__(self):
        # Same two-group layout as SetupView: header chrome on ui_layer,
        # the scrollable rows on rows_layer — and the same forced
        # dirty-rect mode so neither group's first draw wipes the other.
        self.ui_layer = LayeredDirty()
        self.ui_layer._use_update = True
        self.rows_layer = LayeredDirty()
        self.rows_layer._use_update = True

        self._init_ui_elements()

        self.background_color = Color.BLACK.rgb()

    def _init_ui_elements(self):
        self.title_label = header_title("Software")
        self.back_button = corner_button(
            icon=Icon.BACK.glyph(),
            events=ButtonEvents(
                pressed=BUTTON_BACK_PRESSED,
                released=BUTTON_BACK_RELEASED,
            ),
        )
        self.horizontal_line = header_line()

        # Version rows are informational: name as the caption, version in
        # the control column. Base rows carry their own glyphs; any name
        # not in the map came from an extension and gets the puzzle piece.
        base_icons = {"App": Icon.APP, "OS": Icon.OS_IMAGE}
        # Held so reset() can re-read them: extension version entries may be
        # callables, and a pooled view would otherwise pin them to boot.
        self._version_values = [
            (name, row_value(value)) for name, value in component_versions()
        ]
        row_contents = [
            (base_icons.get(name, Icon.EXTENSION).glyph(), name, widget)
            for name, widget in self._version_values
        ]

        # Data reset (Wi-Fi credentials, entered IPs, installed feed) only
        # makes sense on the appliance; a desktop window's data lives in
        # the user's home directory and the OS owns Wi-Fi.
        self.factory_reset_button = None
        if is_raspberry_pi():
            self.factory_reset_button = row_button(
                text=self._FACTORY_RESET_IDLE_TEXT,
                icon=Icon.CHEVRON_RIGHT.glyph(),
                events=ButtonEvents(
                    pressed=FACTORY_RESET_PRESSED,
                    released=FACTORY_RESET_RELEASED,
                ),
            )
            row_contents.append(
                (Icon.FACTORY_RESET.glyph(), "Factory Reset", self.factory_reset_button)
            )

        # Action rows contributed by extensions (none installed = none
        # shown) — the Pro update flow lives here.
        self._extension_rows = []
        for entry in extensions.software_entries:
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
                widgets=[row_icon(icon), row_label(text), control],
            )
            for i, (icon, text, control) in enumerate(row_contents)
        )

        skin = active_skin()
        self.scrollbar = Scrollbar(
            viewport_top=s.row_top,
            viewport_height=skin.height - s.row_top,
            content_height=self.rows.content_height,
            track_margin_bottom=s.row_top - skin.header.line_y,
        )

        self.ui_layer.add(self.title_label, self.back_button)
        self.rows.add_to_layered(self.rows_layer)

    def reset(self, ctx=None) -> None:
        """Back to a first-visit Software screen.

        The arming state is the one that matters: a row left reading "Tap
        again to reset" from a previous visit would make the *first* tap of
        the next visit the destructive one.
        """
        self.scrollbar.reset()
        self.rows.scroll_to(0.0, force=True)
        self.set_factory_reset_armed(False)
        self.release_presses(self.ui_layer, self.rows_layer)

        current = dict(component_versions())
        for name, widget in self._version_values:
            if name in current:
                widget.set_text(current[name])

        for entry, button in self._extension_rows:
            button.set_text(_entry_text(entry))

    def set_factory_reset_armed(self, armed: bool) -> None:
        """Reflect the factory-reset arming state on its row.

        Armed: red warning label prompting the confirming second tap.
        Idle: the neutral default label. No-op if the row was never built
        (desktop builds omit it).
        """
        button = self.factory_reset_button
        if button is None:
            return
        if armed:
            button.set_text(
                self._FACTORY_RESET_ARMED_TEXT, color=Color.LIGHTEST_RED.rgb()
            )
        else:
            button.set_text(
                self._FACTORY_RESET_IDLE_TEXT, color=Color.WHITE.rgb()
            )

    def update(self, dt: float):
        self.ui_layer.update(dt)
        self.rows_layer.update(dt)

        if self.scrollbar.is_scrollable:
            self.scrollbar.update(dt)
            self.rows.scroll_to(self.scrollbar.offset)

    def handle_event(self, event) -> bool:
        if self.scrollbar.handle_event(event, self.rows):
            return False

        self.back_button.handle_event(event)
        self.rows.handle_event(event)

        return False
