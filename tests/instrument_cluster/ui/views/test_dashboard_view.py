"""DashboardView chrome: bezel strips, layout shifts, and the plugin layer.

The gauges themselves are plugins now — their layout and feature gating
are covered in core/test_plugin_manager.py.
"""

import json

import pygame
import pytest

from instrument_cluster.config import ConfigManager
from instrument_cluster.ui.views.dashboard_view import DashboardView
from instrument_cluster.ui.widgets.status_lights_widget import StatusLightsWidget
from instrument_cluster.ui.widgets.slot_dots_widget import SlotDotsWidget


@pytest.fixture
def config_path(tmp_path):
    original_path = ConfigManager.path
    ConfigManager.set_path(tmp_path / "config.json")
    yield ConfigManager.path
    ConfigManager.set_path(original_path)


def _write_config(path, status_lights: bool) -> None:
    path.write_text(json.dumps({"status_lights": status_lights}))
    ConfigManager.reset()


def _status_lights_widgets(view):
    return [s for s in view.widget_layer.sprites() if isinstance(s, StatusLightsWidget)]


def test_view_owns_only_chrome(config_path):
    _write_config(config_path, status_lights=False)
    view = DashboardView()

    # Without the strips the widget layer is empty…
    assert view.widget_layer.sprites() == []
    # …plus the slot dots in ui_layer (drawn last, above the gauges).
    assert view.slot_dots in view.ui_layer
    # …and the plugin layer starts empty (DashboardState links the gauges).
    assert view.plugin_layer.sprites() == []


def test_dyno_button_sits_next_to_setup(config_path):
    _write_config(config_path, status_lights=False)
    view = DashboardView()

    assert view.dyno_button in view.ui_layer
    # Directly right of Setup, same footer row, no overlap.
    assert view.dyno_button.rect.top == view.setup_button.rect.top
    assert view.dyno_button.rect.left >= view.setup_button.rect.right
    # The slot-name label starts after the Dyno button.
    assert view.slot_name.rect.left >= view.dyno_button.rect.right


def test_dyno_button_survives_the_status_lights_reflow(config_path):
    _write_config(config_path, status_lights=False)
    view = DashboardView()

    view.set_status_lights(True)
    assert view.dyno_button in view.ui_layer
    assert view.dyno_button.rect.left >= view.setup_button.rect.right
    # Exactly one Dyno button after the rebuild — no stale duplicate.
    from instrument_cluster.ui.widgets.base.button import Button

    buttons = [s for s in view.ui_layer.sprites() if isinstance(s, Button)]
    assert len(buttons) == 2  # Setup + Dyno


def test_status_lights_on_reserves_the_bezel_strips(config_path):
    _write_config(config_path, status_lights=True)
    view = DashboardView()

    assert view.status_lights_enabled is True
    assert len(_status_lights_widgets(view)) == 2
    assert view._SHIFT_L == DashboardView._STATUS_STRIP_W - 10
    assert view._SHIFT_R == DashboardView._STATUS_STRIP_W - 18


def test_status_lights_off_removes_strips_and_resets_shifts(config_path):
    _write_config(config_path, status_lights=False)
    view = DashboardView()

    assert view.status_lights_enabled is False
    assert _status_lights_widgets(view) == []
    assert view._SHIFT_L == 0
    assert view._SHIFT_R == 0
    # Both derived anchors follow the shift back to the strip-less layout.
    assert view._TRACK_RECT == (186, 454, 352, 94)
    assert view._COLUMN_LEFT == 186 - 352 // 2


def test_reflow_preserves_plugin_sprites(config_path):
    _write_config(config_path, status_lights=False)
    view = DashboardView()

    sprite = pygame.sprite.DirtySprite()
    sprite.image = pygame.Surface((1, 1))
    sprite.rect = sprite.image.get_rect()
    view.plugin_layer.add(sprite)

    view.set_status_lights(True)

    # The chrome rebuilt, but linked plugin sprites survived the reflow.
    assert sprite in view.plugin_layer
    assert len(_status_lights_widgets(view)) == 2


def test_plugin_layer_draws_between_chrome_and_setup_button(config_path):
    _write_config(config_path, status_lights=False)
    view = DashboardView()

    sprite = pygame.sprite.DirtySprite()
    sprite.image = pygame.Surface((4, 4))
    sprite.image.fill((255, 0, 0))
    sprite.rect = sprite.image.get_rect(topleft=(0, 0))
    view.plugin_layer.add(sprite)

    surface = pygame.Surface((1280, 720))
    background = pygame.Surface((1280, 720))
    # Paint twice: LayeredDirty's very first draw repaints its whole
    # background (wiping lower layers for one frame, as it always has);
    # from the second frame on the layers composite by dirty rects.
    view.full_paint(surface, background)
    view.full_paint(surface, background)

    assert surface.get_at((1, 1))[:3] == (255, 0, 0)


def _pixels(surface, rect):
    return pygame.image.tobytes(surface.subsurface(rect).copy(), "RGB")


def test_setup_button_survives_a_background_overwrite(config_path):
    """One-shot dirty flags must never lose the Setup button.

    The historical failure mode (which the old always-dirty default papered
    over): a background blit lands after the button's only repaint, and a
    static sprite then has nothing to ever re-dirty it. The recovery
    contract is full_paint(), which every screen handover goes through.
    """
    _write_config(config_path, status_lights=False)
    surface = pygame.Surface((1280, 720))
    background = pygame.Surface((1280, 720))
    background.fill((0, 0, 0))

    view = DashboardView()
    btn_rect = view.setup_button.rect
    bg_bytes = _pixels(background, btn_rect)

    # A fresh view's very first draw paints everything (initial dirty=1,
    # and LayeredDirty's first draw is a full repaint regardless).
    view.draw(surface, background)
    assert _pixels(surface, btn_rect) != bg_bytes

    # Steady state: a second draw consumes any remaining dirty flags.
    view.draw(surface, background)

    # The race: background overwrites the frame; a plain draw with nothing
    # dirty leaves the button lost.
    surface.blit(background, (0, 0))
    view.draw(surface, background)

    # full_paint re-dirties every sprite and must bring the button back.
    view.full_paint(surface, background)
    assert _pixels(surface, btn_rect) != bg_bytes
