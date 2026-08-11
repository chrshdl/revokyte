"""Widget color editing: palette-reference fields in the widget tree."""

import pygame
import pytest

from instrument_cluster.config import ConfigManager


@pytest.fixture
def app(tmp_path):
    from instrument_cluster.ui.skins import reset_skin_overrides
    from tools.skin_editor.app import EditorApp

    original = ConfigManager.path
    ConfigManager.set_path(tmp_path / "config.json")
    app = EditorApp()
    try:
        yield app
    finally:
        ConfigManager.set_path(original)
        reset_skin_overrides()


def test_color_field_offers_cycler_and_picker(app):
    app.select_view("dashboard")
    app.select_path("dashboard.delta_loss_color", from_tree=True)
    assert len(app.props_panel.steppers_for("dashboard.delta_loss_color")) == 1
    button = app.props_panel.button_for("dashboard.delta_loss_color")
    assert button is not None and button.label_text() == "Choose color…"


def test_choose_color_button_click_opens_the_picker(app):
    # Regression: the button existed but clicking it crashed — the
    # per-field callback passed a path the picker opener didn't accept.
    # Drive it with a real click, like the designer does.
    app.select_view("dashboard")
    app.select_section("Gear")
    button = app.props_panel.button_for("dashboard.gear_color")
    click = pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1
    )
    assert app.props_panel.handle(click)
    assert app.modal is not None
    assert app.modal.current == app.skin_doc.get("dashboard.gear_color")
    # And a pick through this modal lands on the right field.
    app.modal.on_pick("ORANGE")
    assert app.skin_doc.get("dashboard.gear_color") == "ORANGE"


def test_color_cycles_with_undo(app):
    app.select_view("dashboard")
    app.select_path("dashboard.delta_loss_color", from_tree=True)
    before = app.skin_doc.get("dashboard.delta_loss_color")
    app.edit_color("dashboard.delta_loss_color", 1)
    after = app.skin_doc.get("dashboard.delta_loss_color")
    assert after != before
    app.undo_once()
    assert app.skin_doc.get("dashboard.delta_loss_color") == before
    assert not app.any_dirty


def test_color_picker_applies_choice(app):
    app.select_view("dashboard")
    app.select_path("dashboard.delta_loss_color", from_tree=True)
    app.open_color_picker()
    assert app.modal is not None
    # Click the PURPLE cell.
    idx = [c.name for c in app.modal.colors].index("PURPLE")
    from tools.skin_editor.color_picker import CELL_H, CELL_W, COLS

    cell_x = app.modal.grid.x + (idx % COLS) * CELL_W + 10
    cell_y = app.modal.grid.y + (idx // COLS) * CELL_H + 10
    app.modal.handle(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(cell_x, cell_y), button=1)
    )
    assert app.modal is None  # picker closed itself
    assert app.skin_doc.get("dashboard.delta_loss_color") == "PURPLE"
    app.undo_once()
    assert app.skin_doc.get("dashboard.delta_loss_color") == "LIGHT_RED"


def test_color_edit_reaches_the_rendered_widget(app):
    # The delta gauge shows a positive (loss) demo value; recoloring the
    # loss role must change the pixels the rebuilt view renders.
    app.select_view("dashboard")
    app.canvas.set_surface(app.viewhost.render(app.skin_doc.skin))
    from instrument_cluster.ui.colors import Color

    def has_color(rgb):
        view = app.viewhost.surface
        d = app.skin_doc.skin.dashboard
        x, y, w, h = d.delta_rect  # center-anchored
        return any(
            view.get_at((xx, yy))[:3] == rgb
            for yy in range(y - h // 2, y + h // 2, 2)
            for xx in range(x - w // 2, x + w // 2, 2)
        )

    assert has_color(Color.LIGHT_RED.rgb())
    app.skin_doc.set("dashboard.delta_loss_color", "PURPLE")
    app.canvas.set_surface(app.viewhost.render(app.skin_doc.skin))
    assert has_color(Color.PURPLE.rgb())
    assert not has_color(Color.LIGHT_RED.rgb())


def test_invalid_color_name_is_rejected(app):
    with pytest.raises(ValueError):
        app.skin_doc.set("dashboard.delta_loss_color", "NOT_A_COLOR")
