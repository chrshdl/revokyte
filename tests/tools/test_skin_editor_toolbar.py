"""Toolbar Save/Undo/Redo: present, gated on state, functional, with
status-bar feedback — pinned after a designer read the dimmed buttons as
missing."""

import shutil

import pygame
import pytest

from instrument_cluster.config import ConfigManager

from tools.skin_editor import persist


@pytest.fixture
def app(tmp_path, monkeypatch):
    from instrument_cluster.ui.skins import reset_skin_overrides
    from tools.skin_editor.app import EditorApp

    original = ConfigManager.path
    ConfigManager.set_path(tmp_path / "config.json")
    # Redirect skin saves away from the real sources.
    skins_dir = tmp_path / "skins"
    skins_dir.mkdir()
    shutil.copy(
        persist.SKINS_DIR / "skin_1280x720.py", skins_dir / "skin_1280x720.py"
    )
    monkeypatch.setattr(persist, "SKINS_DIR", skins_dir)

    app = EditorApp()
    try:
        yield app
    finally:
        ConfigManager.set_path(original)
        reset_skin_overrides()


def _button(app, label_start: str):
    for b in app.toolbar.buttons:
        if b.label_text().startswith(label_start):
            return b
    raise AssertionError(f"no toolbar button {label_start!r}")


def _click(button):
    return pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1
    )


def test_toolbar_icons_render_in_material_symbols():
    from instrument_cluster.ui.utils import FontFamily, load_font_px

    from tools.skin_editor import uikit

    font = load_font_px(18, FontFamily.MATERIAL_SYMBOLS)
    for name, glyph in [
        ("save", uikit.ICON_SAVE),
        ("undo", uikit.ICON_UNDO),
        ("redo", uikit.ICON_REDO),
    ]:
        metrics = font.metrics(glyph)
        assert metrics and metrics[0] is not None, f"{name} missing from font"
        surf = font.render(glyph, True, (255, 255, 255))
        assert surf.get_bounding_rect().width > 0, f"{name} renders blank"


def test_toolbar_buttons_carry_their_icons(app):
    from tools.skin_editor import uikit

    assert _button(app, "Save").icon == uikit.ICON_SAVE
    assert _button(app, "Undo").icon == uikit.ICON_UNDO
    assert _button(app, "Redo").icon == uikit.ICON_REDO


def test_toolbar_buttons_do_not_overlap(app):
    rects = [b.rect for b in app.toolbar.buttons]
    for i, r1 in enumerate(rects):
        for r2 in rects[i + 1 :]:
            assert not r1.colliderect(r2), f"{r1} overlaps {r2}"


def test_save_and_undo_buttons_gate_on_state(app):
    save, undo, redo = (
        _button(app, "Save"),
        _button(app, "Undo"),
        _button(app, "Redo"),
    )
    assert not save.enabled() and not undo.enabled() and not redo.enabled()
    assert save.label_text() == "Save"

    app.edit_component("dashboard.gear_rect", 0, 5)
    assert save.enabled() and undo.enabled()
    assert save.label_text() == "Save •"  # dirty marker


def test_undo_button_click_reverts_and_flashes(app):
    old = app.skin_doc.get("dashboard.gear_rect")
    app.edit_component("dashboard.gear_rect", 0, 5)

    app.toolbar.handle(_click(_button(app, "Undo")))

    assert app.skin_doc.get("dashboard.gear_rect") == old
    assert not app.any_dirty
    assert "Undid dashboard.gear_rect" in app.flash_text()

    app.toolbar.handle(_click(_button(app, "Redo")))
    assert app.skin_doc.get("dashboard.gear_rect")[0] == old[0] + 5
    assert "Redid dashboard.gear_rect" in app.flash_text()


def test_save_button_click_writes_and_reports(app):
    app.edit_component("dashboard.gear_rect", 0, 5)

    app.toolbar.handle(_click(_button(app, "Save")))

    assert not app.any_dirty
    assert "Saved skin_1280x720.py" in app.flash_text()
    saved = (persist.SKINS_DIR / "skin_1280x720.py").read_text()
    assert "gear_rect=(645, 400, 186, 232)," in saved
