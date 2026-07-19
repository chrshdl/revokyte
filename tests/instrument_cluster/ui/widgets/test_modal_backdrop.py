"""ModalBackdrop: solid scrim, and alpha as dim strength under a pattern."""

import pygame

from instrument_cluster.ui.widgets.base.modal_backdrop import ModalBackdrop


def make_pattern():
    # 2x2 tile: an opaque grey dot top-left, the rest fully transparent.
    pattern = pygame.Surface((2, 2), pygame.SRCALPHA)
    pattern.set_at((0, 0), (40, 40, 40, 255))
    return pattern


def test_solid_scrim_uses_alpha():
    backdrop = ModalBackdrop((4, 4), alpha=200)

    assert backdrop.image.get_at((1, 1)) == (0, 0, 0, 200)


def test_pattern_dots_stay_opaque():
    backdrop = ModalBackdrop((4, 4), alpha=200, pattern=make_pattern())

    assert backdrop.image.get_at((0, 0)) == (40, 40, 40, 255)
    assert backdrop.image.get_at((2, 2)) == (40, 40, 40, 255)  # tiled


def test_pattern_gaps_are_dimmed_by_alpha():
    backdrop = ModalBackdrop((4, 4), alpha=200, pattern=make_pattern())

    assert backdrop.image.get_at((1, 1)) == (0, 0, 0, 200)


def test_set_alpha_rebuilds_the_dim_strength():
    backdrop = ModalBackdrop((4, 4), alpha=100, pattern=make_pattern())

    backdrop.set_alpha(220)

    assert backdrop.image.get_at((1, 1)) == (0, 0, 0, 220)
    assert backdrop.dirty == 1
