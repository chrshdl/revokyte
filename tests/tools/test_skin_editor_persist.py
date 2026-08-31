"""Skin-editor persistence: golden emissions and path editing.

The palette/icons savers rewrite member lines in place — saving an
*unmodified* document must reproduce the source file byte-for-byte
(guards the rewrite patterns against file-layout drift). The skin saver
goes through the shared serializer; here we pin docstring preservation.
"""

import shutil

import pytest

from instrument_cluster.ui.skins import SKIN_1280

from tools.skin_editor import paths, persist
from tools.skin_editor.document import (
    IconsDocument,
    PaletteDocument,
    SkinDocument,
)


@pytest.fixture(autouse=True)
def _reset_overrides():
    from instrument_cluster.ui.colors import reset_palette_overrides
    from instrument_cluster.ui.icons import reset_icon_overrides
    from instrument_cluster.ui.skins import reset_skin_overrides

    yield
    reset_palette_overrides()
    reset_icon_overrides()
    reset_skin_overrides()


def test_unmodified_palette_saves_byte_identical(tmp_path, monkeypatch):
    target = tmp_path / "colors.py"
    shutil.copy(persist.COLORS_PY, target)
    monkeypatch.setattr(persist, "COLORS_PY", target)
    before = target.read_text()
    persist.save_palette(PaletteDocument())
    assert target.read_text() == before


def test_unmodified_icons_save_byte_identical(tmp_path, monkeypatch):
    target = tmp_path / "icons.py"
    shutil.copy(persist.ICONS_PY, target)
    monkeypatch.setattr(persist, "ICONS_PY", target)
    before = target.read_text()
    persist.save_icons(IconsDocument())
    assert target.read_text() == before


def test_palette_edit_rewrites_only_that_member(tmp_path, monkeypatch):
    from instrument_cluster.ui.colors import Color

    target = tmp_path / "colors.py"
    shutil.copy(persist.COLORS_PY, target)
    monkeypatch.setattr(persist, "COLORS_PY", target)

    doc = PaletteDocument()
    doc.set(Color.BLUE, (1, 2, 3))
    persist.save_palette(doc)

    text = target.read_text()
    assert "BLUE = (auto(), (1, 2, 3))" in text
    assert "DARK_BLUE = (auto(), (0, 50, 125))" in text  # neighbours intact
    assert not doc.dirty


def test_icon_edit_writes_escape(tmp_path, monkeypatch):
    from instrument_cluster.ui.icons import Icon

    target = tmp_path / "icons.py"
    shutil.copy(persist.ICONS_PY, target)
    monkeypatch.setattr(persist, "ICONS_PY", target)

    doc = IconsDocument()
    doc.set(Icon.SETTINGS_GEAR, "")
    persist.save_icons(doc)

    assert 'SETTINGS_GEAR = "\\ue000"' in target.read_text()
    assert not doc.dirty


def test_skin_save_preserves_docstring(tmp_path, monkeypatch):
    monkeypatch.setattr(persist, "SKINS_DIR", tmp_path)
    original = persist.PKG / "ui" / "skins" / "skin_1280x720.py"
    shutil.copy(original, tmp_path / "skin_1280x720.py")

    doc = SkinDocument(SKIN_1280)
    doc.set("dashboard.gear_rect", (641, 388, 186, 232))
    saved = persist.save_skin(doc)

    text = saved.read_text()
    assert "The 1280x720 skin" in text  # original docstring survived
    assert "gear_rect=(641, 388, 186, 232)," in text
    assert not doc.dirty


def test_replace_at_round_trips_every_path():
    skin = SKIN_1280
    for path, axis, value in paths.walk(skin):
        if path in ("name", "size"):
            continue
        rebuilt = paths.replace_at(skin, path, value)
        assert rebuilt == skin, path
        # And a real change lands exactly at the path.
        if isinstance(value, tuple):
            changed = tuple(v + 1 for v in value)
        elif isinstance(value, int):
            changed = value + 1
        else:
            continue
        edited = paths.replace_at(skin, path, changed)
        assert paths.get_at(edited, path) == changed, path
        assert edited != skin


def test_car_skin_saves_to_its_own_file_and_round_trips():
    """A car skin shares its resolution with the panel default, so both the
    filename and the emitted symbol have to carry the car id. Without that,
    saving the car skin overwrites the base skin for that panel and the file
    declares a second SKIN_1280."""
    from instrument_cluster.ui.skins import SKIN_1280, SKIN_1280_CAR3588
    from instrument_cluster.ui.skins.serialize import emit_skin_module

    base_path = persist.skin_path(SKIN_1280)
    car_path = persist.skin_path(SKIN_1280_CAR3588)
    assert base_path != car_path
    assert car_path.name == "skin_1280x720_car3588.py"

    emitted = emit_skin_module(
        SKIN_1280_CAR3588, docstring=persist._existing_docstring(car_path)
    )
    assert emitted == car_path.read_text(), "car skin no-op save is not byte-identical"
    assert "SKIN_1280_CAR3588 = Skin(" in emitted
    assert "car_id=3588," in emitted
    # ...and the base skin must not have gained a car_id line.
    base = emit_skin_module(SKIN_1280, docstring=persist._existing_docstring(base_path))
    assert "car_id" not in base
    assert base == base_path.read_text()
