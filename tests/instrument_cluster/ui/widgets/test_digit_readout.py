"""The readout that must not dance.

A clock showing hundredths changes its last digit 100 times a second. In a
proportional face every one of those changes is also a change of width, so
without a fixed grid the whole number squirms sideways while the driver is
trying to read it. These tests pin the two properties that stop it: every
character keeps its slot, and the block keeps its place when the value gains
a digit.
"""

import pygame
import pytest

from instrument_cluster.ui.utils import FontFamily, load_font_px
from instrument_cluster.ui.widgets.base.digit_readout import DigitReadout
from instrument_cluster.ui.widgets.base.digits import digit_metrics

WHITE = (210, 210, 210)
GREY = (120, 120, 120)
GAP = 2
TEMPLATE = "00.00"


@pytest.fixture
def fonts():
    return (
        load_font_px(120, FontFamily.D_DIN_EXP_BOLD),
        load_font_px(38, FontFamily.D_DIN_EXP),
    )


def _readout(fonts, text: str) -> DigitReadout:
    digits, unit = fonts
    readout = DigitReadout(
        pos=(400, 300),
        font=digits,
        color=WHITE,
        template=TEMPLATE,
        unit="sec",
        unit_font=unit,
        unit_color=GREY,
        digit_gap=GAP,
        unit_gap=16,
    )
    readout.set_text(text)
    return readout


def _pixels(surface: pygame.Surface, rect) -> bytes:
    return pygame.image.tostring(surface.subsurface(rect), "RGBA")


def test_the_block_holds_its_place_for_every_value_within_the_template(fonts):
    """Same rect for 0.00 and 99.99: nothing moves as the clock runs."""
    rects = [
        tuple(_readout(fonts, text).rect)
        for text in ("0.00", "9.99", "88.88", "99.99")
    ]
    assert len(set(rects)) == 1, rects


def test_gaining_a_digit_leaves_the_others_exactly_where_they_were(fonts):
    """9.99 -> 10.00 is the one moment a fixed-width field earns itself: the
    hundredths must not jump sideways because a tens digit appeared."""
    digits, _ = fonts
    metrics = digit_metrics(digits, WHITE)
    field_w = metrics.width(TEMPLATE, GAP)
    suffix_w = metrics.width("9.99", GAP)

    short = _readout(fonts, "9.99")
    long = _readout(fonts, "19.99")

    assert short.image.get_size() == long.image.get_size()
    # Everything from the shared suffix rightwards — the unit included.
    region = (
        field_w - suffix_w,
        0,
        short.image.get_width() - (field_w - suffix_w),
        short.image.get_height(),
    )
    assert _pixels(short.image, region) == _pixels(long.image, region)


def test_a_value_wider_than_the_template_keeps_all_of_its_digits(fonts):
    """A run slow enough to pass 100 s is not a reason to drop a digit; the
    block widens instead."""
    normal = _readout(fonts, "99.99")
    wide = _readout(fonts, "123.45")

    assert wide.image.get_width() > normal.image.get_width()
    assert wide.text == "123.45"


def test_the_unit_sits_on_the_digits_baseline(fonts):
    """Bottom-aligning the two surfaces instead would float a smaller unit
    above the line the digits stand on."""
    digits, unit = fonts
    readout = _readout(fonts, "12.55")

    assert readout._unit_top == digits.get_ascent() - unit.get_ascent()
    assert readout._unit_top > 0


def test_setting_the_same_text_again_does_not_redraw(fonts):
    readout = _readout(fonts, "12.55")
    readout.dirty = 0

    readout.set_text("12.55")

    assert readout.dirty == 0
