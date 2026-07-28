"""ModalDimming: dim strength expressed as a percentage."""
import pygame
import pytest

from instrument_cluster.ui.widgets.base.modal_dimming import ModalDimming


@pytest.mark.parametrize(
    "percent, expected_alpha",
    [(0, 0), (35, 89), (50, 128), (100, 255)],
)
def test_alpha_matches_the_requested_percentage(percent, expected_alpha):
    assert ModalDimming.alpha_for(percent) == expected_alpha


def test_percentage_is_out_of_255_not_a_raw_alpha():
    """The point of the class: 35 means 35% dimmer, not alpha 35."""
    assert ModalDimming.alpha_for(35) != 35


def test_fill_is_black_at_the_derived_alpha():
    dimming = ModalDimming((4, 4), percent=35)
    assert dimming.image.get_at((1, 1)) == (0, 0, 0, 89)


def test_compositing_dims_by_the_requested_amount():
    """What the percentage actually promises, measured end to end."""
    surface = pygame.Surface((4, 4))
    surface.fill((200, 200, 200))
    surface.blit(ModalDimming((4, 4), percent=35).image, (0, 0))

    dimmed = surface.get_at((1, 1))[0]
    assert dimmed / 200 == pytest.approx(0.65, abs=0.01)


def test_percent_is_clamped():
    assert ModalDimming((2, 2), percent=-10).percent == 0
    assert ModalDimming((2, 2), percent=150).percent == 100


def test_set_percent_rebuilds_and_dirties():
    dimming = ModalDimming((4, 4), percent=10)
    dimming.dirty = 0

    dimming.set_percent(60)

    assert dimming.percent == 60
    assert dimming.dirty == 1
    assert dimming.image.get_at((1, 1))[3] == ModalDimming.alpha_for(60)
