import pytest

from instrument_cluster.extensions import SetupEntry, runtime as extensions
from instrument_cluster.ui.skins import active_skin
from instrument_cluster.ui.views.setup_rows import row_value
from instrument_cluster.ui.views.software_view import (
    SoftwareView,
    component_versions,
    image_version,
)

APPLIANCE_OS_RELEASE = (
    'NAME="InstrumentCluster-OS"\nID=instrument-cluster\n'
    'BUILD_ID=202608141200\nVERSION_ID="v0.2.31"\n'
    'BUILDROOT_VERSION="2025.02.15"\n'
)


@pytest.fixture
def view(monkeypatch):
    """Appliance-layout view: version rows plus the factory-reset row."""
    monkeypatch.setattr(
        "instrument_cluster.ui.views.software_view.is_raspberry_pi", lambda: True
    )
    return SoftwareView()


@pytest.fixture
def desktop_view(monkeypatch):
    monkeypatch.setattr(
        "instrument_cluster.ui.views.software_view.is_raspberry_pi", lambda: False
    )
    return SoftwareView()


def _texts(view):
    return {
        s.text
        for s in view.rows_layer.sprites()
        if hasattr(s, "text") and isinstance(s.text, str)
    }


# ---------------------------------------------------------------------------
# image_version / component_versions
# ---------------------------------------------------------------------------

def test_image_version_reads_the_appliance_os_release(tmp_path):
    p = tmp_path / "os-release"
    p.write_text(APPLIANCE_OS_RELEASE)
    assert image_version(str(p)) == "v0.2.31"


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


def test_component_versions_on_the_appliance_image(tmp_path):
    p = tmp_path / "os-release"
    p.write_text(APPLIANCE_OS_RELEASE)
    rows = dict(component_versions(str(p)))
    assert rows["OS"] == "v0.2.31"
    assert rows["Buildroot"] == "2025.02.15"
    assert "App" in rows and "Delta Calculator" in rows
    assert [name for name, _ in component_versions(str(p))][:2] == ["App", "OS"]


def test_component_versions_off_the_image(tmp_path):
    # No OS/Buildroot rows on dev machines — a desktop distro's values
    # are not the cluster's.
    names = [n for n, _ in component_versions(str(tmp_path / "missing"))]
    assert names == ["App", "Delta Calculator"]


def test_extension_version_entries_are_appended(tmp_path):
    extensions.version_entries.append(("Pro Extension", lambda: "9.9.9"))
    try:
        rows = component_versions(str(tmp_path / "missing"))
    finally:
        extensions.version_entries.pop()
    assert rows[-1] == ("Pro Extension", "9.9.9")


# ---------------------------------------------------------------------------
# view composition
# ---------------------------------------------------------------------------

def test_appliance_view_has_factory_reset_row(view):
    assert view.factory_reset_button is not None
    assert "Factory Reset" in _texts(view)
    assert "App" in _texts(view)


def test_desktop_view_has_no_factory_reset_row(desktop_view):
    assert desktop_view.factory_reset_button is None
    assert "Factory Reset" not in _texts(desktop_view)
    # Arming must be a no-op, not a crash, when the row was never built.
    desktop_view.set_factory_reset_armed(True)


def test_extension_software_entries_render_after_factory_reset(monkeypatch):
    monkeypatch.setattr(
        "instrument_cluster.ui.views.software_view.is_raspberry_pi", lambda: True
    )
    entry = SetupEntry(
        icon="",
        label="Updates",
        button_text="Check for updates",
        make_state=lambda sm: None,
    )
    extensions.software_entries.append(entry)
    try:
        ext_view = SoftwareView()
    finally:
        extensions.software_entries.pop()
    texts = _texts(ext_view)
    assert {"Updates", "Check for updates"} <= texts
    # Extension rows come last.
    plain_view = SoftwareView()
    assert len(ext_view.rows.rows) == len(plain_view.rows.rows) + 1


def test_row_value_is_ellipsized_to_the_value_column():
    # The string is uncontrolled (dev versions, future fields); overflow
    # would paint past the separator inset into the scrollbar.
    label = row_value("x" * 300)
    skin = active_skin()
    s = skin.setup
    assert label.rect.width <= skin.width - s.separator_inset - s.value_x
    assert label.text.endswith("…")
