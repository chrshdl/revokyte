"""Palette override hook (skin-editor live preview support)."""

import pytest

from instrument_cluster.ui.colors import (
    Color,
    reset_palette_overrides,
    set_palette_override,
)


@pytest.fixture(autouse=True)
def _clean_overrides():
    reset_palette_overrides()
    yield
    reset_palette_overrides()


def test_override_wins_and_reset_restores():
    baked = Color.BLUE.rgb()
    set_palette_override(Color.BLUE, (1, 2, 3))
    assert Color.BLUE.rgb() == (1, 2, 3)
    # Other members are untouched.
    assert Color.RED.rgb() == (200, 0, 0)
    reset_palette_overrides()
    assert Color.BLUE.rgb() == baked


def test_widget_constructed_after_override_picks_it_up():
    # The whole point of moving color defaults to construction time: a
    # rebuilt widget must see the live palette, not import-time captures.
    from instrument_cluster.ui.widgets.gear_widget import GearWidget

    set_palette_override(Color.BLACK, (9, 9, 9))
    set_palette_override(Color.WHITE, (250, 250, 250))
    w = GearWidget(rect=(100, 100, 186, 232))
    assert w.bg_color == (9, 9, 9)
    assert w.text_color == (250, 250, 250)


def test_overlay_builders_pick_up_overrides():
    from instrument_cluster.ui.feed_update_window import _card_color
    from instrument_cluster.ui.no_signal_window import _banner_fill

    set_palette_override(Color.DARKER_GREY, (5, 6, 7))
    set_palette_override(Color.DARK_GREY, (8, 9, 10))
    assert _card_color() == (5, 6, 7)
    assert _banner_fill()[0] == (8, 9, 10)
