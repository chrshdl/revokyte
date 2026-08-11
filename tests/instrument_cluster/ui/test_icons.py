"""Icon registry: every glyph exists in the material-symbols face, and the
override hook (skin-editor live preview) behaves."""

import pytest

from instrument_cluster.ui.icons import (
    Icon,
    reset_icon_overrides,
    set_icon_override,
)
from instrument_cluster.ui.utils import FontFamily, load_font_px


@pytest.fixture(autouse=True)
def _clean_overrides():
    reset_icon_overrides()
    yield
    reset_icon_overrides()


def test_every_icon_renders_in_material_symbols():
    font = load_font_px(40, FontFamily.MATERIAL_SYMBOLS)
    for icon in Icon:
        glyph = icon.glyph()
        assert len(glyph) == 1, icon
        metrics = font.metrics(glyph)
        assert metrics and metrics[0] is not None, f"{icon.name} missing"
        surf = font.render(glyph, True, (255, 255, 255))
        assert surf.get_width() > 0, f"{icon.name} renders empty"
        assert surf.get_bounding_rect().width > 0, f"{icon.name} renders blank"


def test_glyphs_are_private_use_area():
    # Material symbols live in the PUA; a stray ASCII value would render
    # as text in every icon slot.
    for icon in Icon:
        assert 0xE000 <= ord(icon.value) <= 0xF8FF, icon


def test_override_wins_and_reset_restores():
    baked = Icon.SETTINGS_GEAR.glyph()
    set_icon_override(Icon.SETTINGS_GEAR, "")
    assert Icon.SETTINGS_GEAR.glyph() == ""
    assert Icon.LOCK.glyph() == Icon.LOCK.value
    reset_icon_overrides()
    assert Icon.SETTINGS_GEAR.glyph() == baked
