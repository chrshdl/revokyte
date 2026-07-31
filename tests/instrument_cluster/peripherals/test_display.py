import pygame
import pytest

from instrument_cluster.peripherals import display
from instrument_cluster.peripherals.display import (
    DEV,
    RPI_DISPLAY_2,
    WAVESHARE_5,
    WAVESHARE_7,
    _match_by_resolution,
    _resolve_profile,
)


def _finger_down(nx: float, ny: float) -> pygame.event.Event:
    return pygame.event.Event(pygame.FINGERDOWN, {"x": nx, "y": ny})


# --- Resolution auto-detect ---


@pytest.mark.parametrize(
    "size, expected",
    [
        ((720, 1280), RPI_DISPLAY_2),
        ((1024, 600), WAVESHARE_7),
        ((800, 480), WAVESHARE_5),
    ],
)
def test_match_by_resolution_known_panels(size, expected):
    profile = _match_by_resolution(size)
    assert profile is not None
    assert profile.name == expected


def test_match_by_resolution_unknown_size():
    assert _match_by_resolution((1920, 1080)) is None


# --- Profile resolution ---


def test_resolve_explicit_name_wins():
    assert _resolve_profile(WAVESHARE_5).name == WAVESHARE_5


def test_resolve_unknown_name_falls_back(monkeypatch):
    monkeypatch.setattr(display, "is_raspberry_pi", lambda: False)
    assert _resolve_profile("no_such_panel").name == DEV


def test_resolve_on_pi_detects_waveshare_5(monkeypatch):
    monkeypatch.setattr(display, "is_raspberry_pi", lambda: True)
    monkeypatch.setattr(display, "_detect_physical_size", lambda: (800, 480))
    assert _resolve_profile("auto").name == WAVESHARE_5


def test_resolve_on_pi_unrecognized_size_defaults_to_display_2(monkeypatch):
    monkeypatch.setattr(display, "is_raspberry_pi", lambda: True)
    monkeypatch.setattr(display, "_detect_physical_size", lambda: (640, 480))
    assert _resolve_profile(None).name == RPI_DISPLAY_2


# --- Profile invariants ---


def test_waveshare_5_renders_natively():
    profile = _resolve_profile(WAVESHARE_5)
    assert profile.physical_size == (800, 480)
    assert profile.logical_size == profile.physical_size
    assert not profile.uses_hardware_renderer
    assert profile.rotation == 0


# --- Input mapping ---


def test_to_logical_landscape_is_passthrough():
    profile = _resolve_profile(WAVESHARE_5)
    lw, lh = profile.logical_size
    assert profile.to_logical(_finger_down(0.0, 0.0)) == (0, 0)
    assert profile.to_logical(_finger_down(0.5, 0.5)) == (lw // 2, lh // 2)
    assert profile.to_logical(_finger_down(1.0, 1.0)) == (lw, lh)


def test_to_logical_rotated_panel_inverts_x():
    profile = _resolve_profile(RPI_DISPLAY_2)
    lw, lh = profile.logical_size
    assert profile.to_logical(_finger_down(0.0, 0.0)) == (lw, 0)
    assert profile.to_logical(_finger_down(1.0, 1.0)) == (0, lh)
