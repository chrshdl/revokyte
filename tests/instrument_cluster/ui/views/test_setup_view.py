import pytest

from instrument_cluster.config import ConfigManager
from instrument_cluster.extensions import SetupEntry, runtime as extensions
from instrument_cluster.ui.skins import active_skin
from instrument_cluster.ui.views.setup_view import SetupView, image_version


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
    s = active_skin().setup
    row_top = s.row_top
    pitch = s.row_pitch
    # Dropdown headers and row action buttons are stretched vertically to
    # fill the row's grid cell, minus a small clearance that keeps the
    # separator lines visible (see SetupView._row_dropdown and ._row_button);
    # the brightness widget is not, and sits at the row's natural top.
    dropdown_offset = (s.row_pitch - s.row_height) // 2 - s.separator_clearance

    assert view.telemetry_mode_dropdown.rect.topleft == (
        s.dropdown_x,
        row_top + 0 * pitch - dropdown_offset,
    )
    assert view.diff_reference_mode_dropdown.rect.topleft == (
        s.dropdown_x,
        row_top + 2 * pitch - dropdown_offset,
    )
    # The status-lights toggle shares the stretched dropdown-header rect.
    assert view.status_lights_toggle.rect.topleft == (
        s.dropdown_x,
        row_top + 3 * pitch - dropdown_offset,
    )
    assert view.wifi_button.rect.topleft == (
        s.dropdown_x,
        row_top + 4 * pitch - dropdown_offset,
    )
    # BrightnessWidget centers its stepper buttons within the row band, with
    # its own small internal offset from the row's natural top.
    assert view.brightness_widget.minus_button.rect.topleft == (
        s.value_x,
        row_top + 1 * pitch + 2,
    )
    assert view.brightness_widget.plus_button.rect.topleft == (
        s.value_x + 434,
        row_top + 1 * pitch + 2,
    )


def test_open_dropdown_menu_lists_every_option_full_row_width(view):
    # The open menu shows all options (including the current selection, each
    # with its own radio button), starting at the same x as the closed
    # header and extending to the row's right edge — not the header's
    # narrower width, but never reaching left of it (that would cover the
    # row's caption label).
    skin = active_skin()
    s = skin.setup
    expected_x = s.dropdown_x
    expected_width = skin.width - s.separator_inset - s.dropdown_x

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
    pitch = active_skin().setup.row_pitch
    cell_bottom = last_row.base_bottom + (pitch - last_row.height) / 2
    viewport_bottom = view.scrollbar.viewport_top + view.scrollbar.viewport_height

    assert cell_bottom - view.scrollbar.max_offset <= viewport_bottom


def test_scrollbar_track_has_equal_top_and_bottom_margins(view):
    # The visual track starts ROW_TOP - header-line-y below the header line;
    # it must keep the same breathing room from the screen bottom instead of
    # running flush to the edge. Only the track shrinks — the scroll range
    # (max_offset) still spans the full viewport.
    skin = active_skin()
    s = skin.setup
    top_margin = s.row_top - skin.header.line_y
    track = view.scrollbar._track_rect()

    assert track.top == s.row_top
    assert skin.height - track.bottom == top_margin
    assert view.scrollbar.viewport_rect().bottom == skin.height


@pytest.mark.parametrize("profile", ["dev", "waveshare_7", "waveshare_5"])
def test_open_dropdown_stays_clear_of_the_header_line(
    tmp_path, monkeypatch, force_profile, profile
):
    """The open menu's scrim blanks everything under its footprint — if the
    footprint climbs onto the header line, the line visibly disappears
    under the dropdown (shipped on the 800x480 skin via a half-pixel
    banker's rounding in the stretched-cell offset). A width-2 line at
    line_y covers rows line_y..line_y+1, so the footprint must start at
    line_y + 2 or below."""
    monkeypatch.setattr(
        "instrument_cluster.ui.views.setup_view.is_raspberry_pi", lambda: True
    )
    original_path = ConfigManager.path
    ConfigManager.set_path(tmp_path / "config.json")
    try:
        with force_profile(profile):
            view = SetupView()
            dropdown = view.telemetry_mode_dropdown
            dropdown._set_open(True)
            footprint = dropdown.rect.unionall(
                [r for _, r in dropdown.get_option_rects()]
            )
            line_bottom = active_skin().header.line_y + 1
            assert footprint.top > line_bottom, (
                f"{profile}: open dropdown footprint {footprint} covers the "
                f"header line (bottom row {line_bottom})"
            )
    finally:
        ConfigManager.set_path(original_path)


def test_status_lights_toggle_reflects_config_default(view):
    # Fresh config defaults to status lights off.
    assert view.status_lights_toggle.checked is False


def test_set_brightness_text_updates_percent_label(view):
    view.set_brightness_text(80)
    assert view.brightness_widget.percent_label.text == "80 %"


def test_base_view_has_no_extension_rows(view):
    # With no extension wired, Setup ends at the About row (appliance:
    # Telemetry, Brightness, Reference Lap, Status Lights, Network,
    # Factory Reset, About).
    assert len(view.rows.rows) == 7


def test_extension_entries_append_rows_in_order(view, extension_entries):
    ext_view = SetupView()
    assert len(ext_view.rows.rows) == 7 + len(extension_entries)
    # About stays the last row — extension rows insert above it.
    assert ext_view.version_label in ext_view.rows.rows[-1].sprites()


def test_all_row_sprites_are_in_the_rows_layer(view):
    layer_sprites = set(view.rows_layer.sprites())
    for row in view.rows:
        for sprite in row.sprites():
            assert sprite in layer_sprites


def test_desktop_view_hides_appliance_only_rows(desktop_view):
    assert len(desktop_view.rows.rows) == 4
    texts = {
        s.text
        for s in desktop_view.rows_layer.sprites()
        if hasattr(s, "text") and isinstance(s.text, str)
    }
    assert "Brightness" not in texts
    assert "Network" not in texts
    assert "Factory Reset" not in texts
    assert {"Telemetry Mode", "Reference Lap", "Status Lights", "About"} <= texts


def test_version_row_is_last_and_shows_app_version(view):
    # The About row exists on every platform: support and (on the
    # commercial build) traceability need the running version readable on
    # the device, not only in dist metadata.
    assert view.version_label in view.rows.rows[-1].sprites()
    assert view.version_label.text.startswith("App ")
    # Display drops the PEP-440 local segment (dev builds append
    # +g<hash>.d<date>); the release part must always be shown.
    assert view.app_version.split("+", 1)[0] in view.version_label.text


def test_version_label_is_ellipsized_to_the_value_column(
    tmp_path, monkeypatch
):
    # The string is uncontrolled (dev versions, future fields); overflow
    # would paint past the separator inset into the scrollbar.
    monkeypatch.setattr(
        "instrument_cluster.ui.views.setup_view.is_raspberry_pi", lambda: True
    )
    monkeypatch.setattr(
        "instrument_cluster.ui.views.setup_view.image_version",
        lambda path=None: "v0.2.29-with-an-absurdly-long-build-annotation",
    )
    original_path = ConfigManager.path
    ConfigManager.set_path(tmp_path / "config.json")
    try:
        view = SetupView()
        skin = active_skin()
        s = skin.setup
        available = skin.width - s.separator_inset - s.value_x
        assert view.version_label.rect.width <= available
        assert view.version_label.text.endswith("…")
    finally:
        ConfigManager.set_path(original_path)


def test_image_version_reads_the_appliance_os_release(tmp_path):
    p = tmp_path / "os-release"
    p.write_text(
        'NAME="InstrumentCluster-OS"\nID=instrument-cluster\n'
        "BUILD_ID=202608141200\nVERSION_ID=\"v0.2.29\"\n"
    )
    assert image_version(str(p)) == "v0.2.29"


def test_image_version_falls_back_to_build_id_on_untagged_builds(tmp_path):
    # Local/PR image builds carry no VERSION_ID (CI injects it on tags
    # only); the BUILD_ID timestamp still identifies the build.
    p = tmp_path / "os-release"
    p.write_text('ID=instrument-cluster\nBUILD_ID=202608141200\n')
    assert image_version(str(p)) == "202608141200"


def test_image_version_ignores_foreign_os_releases(tmp_path):
    # A desktop distro or stock Raspberry Pi OS has its own os-release;
    # its VERSION_ID is the distro's, not the cluster image's.
    p = tmp_path / "os-release"
    p.write_text('ID=debian\nVERSION_ID="12"\nBUILD_ID=20260814\n')
    assert image_version(str(p)) is None
    assert image_version(str(tmp_path / "missing")) is None


def test_desktop_set_brightness_text_is_harmless(desktop_view):
    # SetupState.enter calls this unconditionally; with the row hidden it
    # must not raise.
    desktop_view.set_brightness_text(70)
    assert desktop_view.brightness_widget.percent_label.text == "70 %"
