"""Widget registry: building blocks, anchor conversion, font scaling."""

import pytest

from instrument_cluster.ui.widgets import registry


def test_every_entry_builds_at_its_default_rect():
    for type_id, entry in registry.REGISTRY.items():
        widgets = registry.build(type_id, entry.default_rect)
        assert widgets, type_id
        for w in widgets:
            assert w.font_scale == pytest.approx(1.0), type_id


def test_tire_grid_builds_four_cells():
    widgets = registry.build("tire-temps", (0, 0, 248, 188))
    assert len(widgets) == 4


def test_font_scale_follows_the_rect_size():
    x, y, w, h = registry.REGISTRY["gear"].default_rect
    doubled = registry.build("gear", (0, 0, w * 2, h * 2))[0]
    assert doubled.font_scale == pytest.approx(2.0)
    halved = registry.build("gear", (0, 0, w // 2, h // 2))[0]
    assert halved.font_scale == pytest.approx(0.5)


def test_font_scale_is_uniform_on_distorted_rects():
    """A stretched box must not distort text: the smaller axis wins."""
    x, y, w, h = registry.REGISTRY["speed"].default_rect
    wide = registry.build("speed", (0, 0, w * 3, h))[0]
    assert wide.font_scale == pytest.approx(1.0)


def test_scaled_gear_renders_larger_glyph():
    import pygame

    def drawn_height(widget):
        widget.set_value(4)
        mask = pygame.mask.from_threshold(
            widget.image, (255, 255, 255), (200, 200, 200, 255)
        )
        rects = mask.get_bounding_rects()
        return max((r.height for r in rects), default=0)

    x, y, w, h = registry.REGISTRY["gear"].default_rect
    normal = drawn_height(registry.build("gear", (0, 0, w, h))[0])
    big = drawn_height(registry.build("gear", (0, 0, w * 2, h * 2))[0])
    assert big > normal * 1.5


def test_color_reaches_colorable_widgets_value_only():
    from instrument_cluster.ui.colors import Color

    gear_rect = registry.REGISTRY["gear"].default_rect
    w = registry.build("gear", gear_rect, color="#EF4444")[0]
    assert w.value_color == (239, 68, 68)
    assert w.text_color == Color.WHITE.rgb()  # header stays white


def test_color_is_ignored_on_non_colorable_widgets():
    delta_rect = registry.REGISTRY["delta"].default_rect
    w = registry.build("delta", delta_rect, color="#EF4444")[0]
    assert w.value_color is None


def test_malformed_color_costs_the_tint_not_the_widget():
    gear_rect = registry.REGISTRY["gear"].default_rect
    w = registry.build("gear", gear_rect, color="#nope99")[0]
    assert w.value_color is None


def test_colored_gear_draws_red_value_under_white_header():
    import pygame

    gear_rect = registry.REGISTRY["gear"].default_rect
    w = registry.build("gear", gear_rect, color="#EF4444")[0]
    w.set_value(4)
    from instrument_cluster.ui.colors import Color

    red = pygame.mask.from_threshold(
        w.image, (239, 68, 68, 255), (60, 60, 60, 255)
    )
    white = pygame.mask.from_threshold(
        w.image, (*Color.WHITE.rgb(), 255), (10, 10, 10, 255)
    )
    assert red.count() > 0  # the value glyph
    assert white.count() > 0  # the header


def test_border_override_reaches_the_widget():
    # None keeps each class's default: current-lap draws a border,
    # gear deliberately doesn't.
    lap_rect = registry.REGISTRY["current-lap"].default_rect
    gear_rect = registry.REGISTRY["gear"].default_rect
    assert registry.build("current-lap", lap_rect)[0].show_border is True
    assert registry.build("gear", gear_rect)[0].show_border is False
    # Explicit overrides win in both directions.
    assert (
        registry.build("current-lap", lap_rect, border=False)[0].show_border
        is False
    )
    assert registry.build("gear", gear_rect, border=True)[0].show_border is True
