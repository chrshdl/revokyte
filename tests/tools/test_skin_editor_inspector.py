"""The widget inspector: clicking a widget in the tree shows all of its
properties; canvas selection reveals the owning widget."""

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


def test_selecting_a_widget_shows_all_its_properties(app):
    app.select_view("dashboard")
    app.select_section("Gear")
    shown = {ed["path"] for ed in app.props_panel._editors}
    assert shown == {
        "dashboard.gear_rect",
        "dashboard.fonts.gear",
        "dashboard.fonts.gear_family",
        "dashboard.gear_color",
        # Panel styling: skinnable so a car skin can wear a light gear panel
        # with a dark numeral and a grey border (skin_1280x720_car3588).
        "dashboard.gear_gradient_top",
        "dashboard.gear_gradient_bottom",
        "dashboard.gear_border_color",
        "dashboard.gear_border_width",
        "dashboard.gear_border_radius",
        "dashboard.gear_header_color",
        "dashboard.gear_header_text",
        "dashboard.gear_shadow_depth_pct",
        "dashboard.gear_shadow_color",
        "dashboard.gear_bevel_light",
        "dashboard.gear_bevel_dark",
        "dashboard.gear_bevel_width",
    }
    # Every editor is functional: rect has 4 steppers, the rest 1 each.
    assert len(app.props_panel.steppers_for("dashboard.gear_rect")) == 4
    assert len(app.props_panel.steppers_for("dashboard.gear_color")) == 1
    assert app.props_panel.button_for("dashboard.gear_color") is not None


def test_selecting_a_field_shows_its_whole_widget_with_highlight(app):
    app.select_view("dashboard")
    app.select_path("dashboard.fonts.gear", from_tree=True)
    assert app.selected_section == "Gear"
    shown = {ed["path"] for ed in app.props_panel._editors}
    assert "dashboard.gear_rect" in shown  # sibling fields visible too


def test_canvas_selection_reveals_the_owning_widget(app):
    app.select_view("dashboard")
    gear = next(
        b for b in app.canvas.bindings if b.path == "dashboard.gear_rect"
    )
    app._canvas_selected(gear)
    assert app.selected_section == "Gear"
    assert "Gear" in app.tree_panel.expanded
    assert app.tree_panel.tree.selected_key == "dashboard.gear_rect"


def test_tree_sections_collapse_and_expand(app):
    app.select_view("dashboard")
    rows_collapsed = len(app.tree_panel.tree.rows)
    app.tree_panel._pick_field("#Gear")
    assert "Gear" in app.tree_panel.expanded
    assert len(app.tree_panel.tree.rows) > rows_collapsed
    assert app.selected_section == "Gear"
    app.tree_panel._pick_field("#Gear")
    assert "Gear" not in app.tree_panel.expanded


def test_every_plain_gauge_has_a_color_field(app):
    from tools.skin_editor import view_tree

    tree = dict(view_tree.tree_for("dashboard"))
    for section, field in [
        ("Gear", "dashboard.gear_color"),
        ("Speed", "dashboard.speed_color"),
        ("Fastest lap", "dashboard.fastest_lap_color"),
        ("Predicted lap", "dashboard.predicted_lap_color"),
        ("Previous lap", "dashboard.lap_time_color"),
        ("Lap counter", "dashboard.lap_counter_color"),
        ("Track name", "dashboard.track_color"),
        ("Fuel pair", "dashboard.fuel_per_lap_color"),
        ("Fuel pair", "dashboard.fuel_laps_color"),
    ]:
        assert field in tree[section], f"{section} lacks {field}"


def test_gauge_value_color_reaches_the_render(app):
    from instrument_cluster.ui.colors import Color

    app.select_view("dashboard")
    app.skin_doc.set("dashboard.gear_color", "ORANGE")
    app.canvas.set_surface(app.viewhost.render(app.skin_doc.skin))
    view = app.viewhost.surface
    d = app.skin_doc.skin.dashboard
    x, y, w, h = d.gear_rect
    found = any(
        view.get_at((xx, yy))[:3] == Color.ORANGE.rgb()
        for yy in range(y - h // 2, y + h // 2, 2)
        for xx in range(x - w // 2, x + w // 2, 2)
    )
    assert found, "gear value did not recolor"
