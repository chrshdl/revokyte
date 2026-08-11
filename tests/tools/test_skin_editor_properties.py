"""Properties-panel steppers: hit-targets must be where the pixels are.

A draw-time rect shift once left every stepper painted 40px below its
hit-target: single steppers were dead (title_font_size), and clicks on a
stacked stepper's lower half hit the neighbour below (predicted_lap_rect's
x minus edited y). These tests pin the fix from both sides: the minus
glyph's ink is inside the stepper's hit zone, and synthetic clicks at the
stepper's own rect edit exactly the intended component.
"""

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


def _click(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1)


def _release(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1)


def _press_minus(app, stepper):
    minus, _mid, _plus = stepper._zones()
    app.props_panel.handle(_click(minus.center))
    app.props_panel.handle(_release(minus.center))


def test_single_stepper_minus_decrements(app):
    # The reported case: Setup view, Header, title_font_size.
    app.select_view("setup")
    app.select_path("header.title_font_size", from_tree=True)
    before = app.skin_doc.get("header.title_font_size")

    steppers = app.props_panel.steppers_for("header.title_font_size")
    assert len(steppers) == 1
    _press_minus(app, steppers[0])

    assert app.skin_doc.get("header.title_font_size") == before - 2  # font step


def test_rect_stepper_edits_only_its_component(app):
    # The reported case: Dashboard view, predicted_lap_rect — minus on x
    # must change x, not y.
    app.select_view("dashboard")
    app.select_path("dashboard.predicted_lap_rect", from_tree=True)
    before = app.skin_doc.get("dashboard.predicted_lap_rect")

    steppers = app.props_panel.steppers_for("dashboard.predicted_lap_rect")
    assert len(steppers) == 4  # x / y / w / h

    _press_minus(app, steppers[0])
    after = app.skin_doc.get("dashboard.predicted_lap_rect")
    assert after[0] == before[0] - 1, "x must decrease"
    assert after[1:] == before[1:], "y/w/h must be untouched"

    # And the y stepper edits y alone.
    _press_minus(app, steppers[1])
    after2 = app.skin_doc.get("dashboard.predicted_lap_rect")
    assert after2[1] == after[1] - 1
    assert (after2[0], after2[2], after2[3]) == (after[0], after[2], after[3])


def test_stepper_ink_is_inside_its_hit_zone(app):
    # Pin the draw==hit alignment itself: after drawing the panel, the "-"
    # glyph's accent-colored ink must sit inside the stepper's minus zone
    # (a future draw-time offset would move the ink out of it).
    from tools.skin_editor import uikit

    app.select_view("setup")
    app.select_path("header.title_font_size", from_tree=True)
    stepper = app.props_panel.steppers_for("header.title_font_size")[0]

    app.props_panel.draw(app.screen)
    minus, _mid, _plus = stepper._zones()

    def is_accent_ink(px):
        # The minus glyph is accent blue, antialiased over the dark row
        # fill — no background color in the panel has a blue channel this
        # strong (theme backgrounds stay below ~70).
        r, g, b = px[:3]
        return b > 120 and b > r + 40

    assert uikit.THEME["accent"][2] > 120  # predicate matches the theme
    hit = any(
        is_accent_ink(app.screen.get_at((xx, yy)))
        for yy in range(minus.top, minus.bottom)
        for xx in range(minus.left, minus.right)
    )
    assert hit, "minus glyph is not drawn inside its hit zone"


def test_steppers_do_not_overlap_each_other_or_the_title(app):
    app.select_view("dashboard")
    app.select_path("dashboard.predicted_lap_rect", from_tree=True)
    rects = [s.rect for s in app.props_panel.steppers]
    title_block_bottom = app.props_panel.rect.y + app.props_panel.FIELDS_TOP
    for r in rects:
        assert r.top > title_block_bottom
    for i, r1 in enumerate(rects):
        for r2 in rects[i + 1 :]:
            assert not r1.colliderect(r2)
