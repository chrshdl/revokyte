"""Inline value entry: double-click a stepper's value, type, Enter/Esc.

Drives the real app with synthetic events — double-click detection,
select-all-on-entry, absolute commit through the normal edit pipeline
(clamping + undo), Esc discard, and the keyboard capture that keeps app
shortcuts from firing mid-entry.
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


def _double_click(app, pos):
    down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1)
    app.props_panel.handle(down)
    app.props_panel.handle(down)  # same tick — well inside the window


def _type(app, *keys):
    for key in keys:
        if isinstance(key, str):
            event = pygame.event.Event(
                pygame.KEYDOWN, key=ord(key), unicode=key
            )
        else:
            event = pygame.event.Event(pygame.KEYDOWN, key=key, unicode="")
        # The app routes KEYDOWN to an open entry before its shortcuts.
        if not app.props_panel.handle_key(event):
            app._key(event)


def _open_entry(app, path, component=0):
    app.select_path(path, from_tree=True)
    stepper = app.props_panel.steppers[component]
    _double_click(app, stepper._zones()[1].center)
    assert stepper.editing
    return stepper


def test_type_and_enter_sets_absolute_value(app):
    app.select_view("setup")
    _open_entry(app, "header.title_font_size")
    _type(app, "4", "4", pygame.K_RETURN)
    assert app.skin_doc.get("header.title_font_size") == 44
    # One undo entry restores the previous value.
    app.undo_once()
    assert app.skin_doc.get("header.title_font_size") == 50


def test_first_keystroke_replaces_the_selected_value(app):
    app.select_view("setup")
    stepper = _open_entry(app, "header.title_font_size")
    assert stepper._buffer == "50" and stepper._select_all
    _type(app, "7")
    assert stepper._buffer == "7"  # replaced, not "507"


def test_escape_discards(app):
    app.select_view("setup")
    stepper = _open_entry(app, "header.title_font_size")
    _type(app, "9", "9", pygame.K_ESCAPE)
    assert not stepper.editing
    assert app.skin_doc.get("header.title_font_size") == 50
    assert not app.any_dirty


def test_rect_component_entry_edits_only_that_component(app):
    app.select_view("dashboard")
    before = app.skin_doc.get("dashboard.predicted_lap_rect")
    _open_entry(app, "dashboard.predicted_lap_rect", component=1)  # y
    _type(app, "2", "0", "0", pygame.K_RETURN)
    after = app.skin_doc.get("dashboard.predicted_lap_rect")
    assert after[1] == 200
    assert (after[0], after[2], after[3]) == (before[0], before[2], before[3])


def test_entered_value_is_clamped_like_any_edit(app):
    app.select_view("setup")
    _open_entry(app, "header.title_font_size")
    _type(app, "3", pygame.K_RETURN)  # below the font floor
    assert app.skin_doc.get("header.title_font_size") == 8


def test_keys_are_captured_while_editing(app):
    app.select_view("dashboard")
    app.select_path("dashboard.predicted_lap_rect", from_tree=True)
    rect_before = app.skin_doc.get("dashboard.predicted_lap_rect")
    stepper = _open_entry(app, "dashboard.predicted_lap_rect", component=0)
    # Arrow keys must type-noop, not nudge the canvas selection.
    _type(app, pygame.K_LEFT, pygame.K_LEFT)
    assert stepper.editing
    assert app.skin_doc.get("dashboard.predicted_lap_rect") == rect_before
    _type(app, pygame.K_ESCAPE)


def test_empty_entry_on_enter_discards(app):
    app.select_view("setup")
    stepper = _open_entry(app, "header.title_font_size")
    _type(app, pygame.K_BACKSPACE, pygame.K_RETURN)
    assert not stepper.editing
    assert app.skin_doc.get("header.title_font_size") == 50


def test_family_cycler_does_not_offer_entry(app):
    app.select_view("setup")
    app.select_path("header.title_font_family", from_tree=True)
    stepper = app.props_panel.steppers[0]
    _double_click(app, stepper._zones()[1].center)
    assert not stepper.editing  # names cycle; they are not typed
