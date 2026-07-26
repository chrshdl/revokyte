import pytest

from instrument_cluster.config import ConfigManager
from instrument_cluster.extensions import SetupEntry, runtime as extensions
from instrument_cluster.ui.constants import (
    HEADER_LINE_TOPLEFT,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
)
from instrument_cluster.ui.views.setup_view import SetupView
from instrument_cluster.ui.widgets.base.list_item import ListItem


@pytest.fixture
def view(tmp_path, monkeypatch):
    """Appliance-layout view: the full row set, including the Pi-only
    Brightness and Network rows."""
    monkeypatch.setattr(
        "instrument_cluster.ui.views.setup_view.is_raspberry_pi", lambda: True
    )
    original_path = ConfigManager.path
    ConfigManager.set_path(tmp_path / "config.json")
    try:
        yield SetupView()
    finally:
        ConfigManager.set_path(original_path)


@pytest.fixture
def desktop_view(tmp_path, monkeypatch):
    """Desktop-layout view: no backlight, no appliance Wi-Fi."""
    monkeypatch.setattr(
        "instrument_cluster.ui.views.setup_view.is_raspberry_pi", lambda: False
    )
    original_path = ConfigManager.path
    ConfigManager.set_path(tmp_path / "config.json")
    try:
        yield SetupView()
    finally:
        ConfigManager.set_path(original_path)


@pytest.fixture
def extension_entries():
    """Register two Setup rows the way a wired extension would. Views
    built while this fixture is active render them after the base
    rows."""
    entries = [
        SetupEntry(
            icon="",
            label="Cloud",
            button_text="Cloud Sync",
            make_state=lambda sm: None,
        ),
        SetupEntry(
            icon="",
            label="Account",
            button_text="Manage Account",
            make_state=lambda sm: None,
        ),
    ]
    extensions.setup_entries.extend(entries)
    try:
        yield entries
    finally:
        del extensions.setup_entries[-len(entries):]


def test_rows_place_controls_on_the_grid(view):
    row_top = ListItem.ROW_TOP
    pitch = ListItem.ROW_PITCH
    # Dropdown headers and row action buttons are stretched vertically to
    # fill the row's grid cell, minus a small clearance that keeps the
    # separator lines visible (see SetupView._row_dropdown and ._row_button);
    # the brightness widget is not, and sits at the row's natural top.
    dropdown_offset = (
        ListItem.ROW_PITCH - ListItem.DEFAULT_HEIGHT
    ) // 2 - ListItem.SEPARATOR_CLEARANCE

    assert view.telemetry_mode_dropdown.rect.topleft == (
        ListItem.DROPDOWN_X,
        row_top + 0 * pitch - dropdown_offset,
    )
    assert view.diff_reference_mode_dropdown.rect.topleft == (
        ListItem.DROPDOWN_X,
        row_top + 2 * pitch - dropdown_offset,
    )
    # The status-lights toggle shares the stretched dropdown-header rect.
    assert view.status_lights_toggle.rect.topleft == (
        ListItem.DROPDOWN_X,
        row_top + 3 * pitch - dropdown_offset,
    )
    assert view.wifi_button.rect.topleft == (
        ListItem.DROPDOWN_X,
        row_top + 4 * pitch - dropdown_offset,
    )
    # BrightnessWidget centers its stepper buttons within the row band, with
    # its own small internal offset from the row's natural top.
    assert view.brightness_widget.minus_button.rect.topleft == (
        ListItem.VALUE_X,
        row_top + 1 * pitch + 2,
    )
    assert view.brightness_widget.plus_button.rect.topleft == (
        ListItem.VALUE_X + 434,
        row_top + 1 * pitch + 2,
    )


def test_open_dropdown_menu_lists_every_option_full_row_width(view):
    # The open menu shows all options (including the current selection, each
    # with its own radio button), starting at the same x as the closed
    # header and extending to the row's right edge — not the header's
    # narrower width, but never reaching left of it (that would cover the
    # row's caption label).
    expected_x = ListItem.DROPDOWN_X
    expected_width = SCREEN_WIDTH - ListItem.SEPARATOR_INSET - ListItem.DROPDOWN_X

    for dropdown in (
        view.telemetry_mode_dropdown,
        view.diff_reference_mode_dropdown,
    ):
        option_rects = dropdown.get_option_rects()
        assert len(option_rects) == len(dropdown.options)
        assert [idx for idx, _ in option_rects] == list(range(len(dropdown.options)))
        for _, rect in option_rects:
            assert rect.x == expected_x
            assert rect.width == expected_width
        # each option sits menu_pitch below the header, in order
        tops = [rect.y for _, rect in option_rects]
        assert tops == sorted(tops)


def test_max_scroll_brings_the_last_rows_full_cell_into_view(view, extension_entries):
    # The stretched row controls fill the row's grid cell, which extends
    # half the inter-row gap beyond the content band. At max scroll the
    # last cell's bottom must land inside the viewport — otherwise the
    # last row's button is clipped by the screen edge. Extension-
    # contributed rows push the list past the viewport, making it scroll.
    view = SetupView()
    assert view.scrollbar.is_scrollable
    last_row = view.rows.rows[-1]
    cell_bottom = last_row.design_bottom + (ListItem.ROW_PITCH - last_row.height) / 2
    viewport_bottom = view.scrollbar.viewport_top + view.scrollbar.viewport_height

    assert cell_bottom - view.scrollbar.max_offset <= viewport_bottom


def test_scrollbar_track_has_equal_top_and_bottom_margins(view):
    # The visual track starts ROW_TOP - header-line-y below the header line;
    # it must keep the same breathing room from the screen bottom instead of
    # running flush to the edge. Only the track shrinks — the scroll range
    # (max_offset) still spans the full viewport.
    top_margin = ListItem.ROW_TOP - HEADER_LINE_TOPLEFT[1]
    track = view.scrollbar._track_rect()

    assert track.top == ListItem.ROW_TOP
    assert SCREEN_HEIGHT - track.bottom == top_margin
    assert view.scrollbar.viewport_rect().bottom == SCREEN_HEIGHT


def test_status_lights_toggle_reflects_config_default(view):
    # Fresh config defaults to status lights off.
    assert view.status_lights_toggle.checked is False


def test_set_brightness_text_updates_percent_label(view):
    view.set_brightness_text(80)
    assert view.brightness_widget.percent_label.text == "80 %"


def test_base_view_has_no_extension_rows(view):
    # With no extension wired, Setup ends at the Network row.
    assert len(view.rows.rows) == 5


def test_extension_entries_append_rows_in_order(view, extension_entries):
    ext_view = SetupView()
    assert len(ext_view.rows.rows) == 5 + len(extension_entries)


def test_all_row_sprites_are_in_the_rows_layer(view):
    layer_sprites = set(view.rows_layer.sprites())
    for row in view.rows:
        for sprite in row.sprites():
            assert sprite in layer_sprites


def test_desktop_view_hides_appliance_only_rows(desktop_view):
    assert len(desktop_view.rows.rows) == 3
    texts = {
        s.text
        for s in desktop_view.rows_layer.sprites()
        if hasattr(s, "text") and isinstance(s.text, str)
    }
    assert "Brightness" not in texts
    assert "Network" not in texts
    assert {"Telemetry Mode", "Reference Lap", "Status Lights"} <= texts


def test_desktop_set_brightness_text_is_harmless(desktop_view):
    # SetupState.enter calls this unconditionally; with the row hidden it
    # must not raise.
    desktop_view.set_brightness_text(70)
    assert desktop_view.brightness_widget.percent_label.text == "70 %"
