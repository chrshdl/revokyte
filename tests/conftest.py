import os

# run pygame in headless mode
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame
import pytest


@pytest.fixture(scope="session", autouse=True)
def pygame_session():
    pygame.init()
    pygame.display.init()
    # minimal dummy window; required for some font/rendering code paths
    pygame.display.set_mode((1, 1))
    yield
    pygame.quit()


@pytest.fixture
def force_profile():
    """Context manager fixture forcing a display profile for a test.

    Usage::

        def test_x(force_profile):
            with force_profile("waveshare_5"):
                ...  # active_profile()/active_skin() resolve to the 5" panel

    Restores the previous profile (usually the lazy dev default) on exit, so
    profile-dependent construction in other tests is unaffected.
    """
    from contextlib import contextmanager

    from instrument_cluster.peripherals import display

    @contextmanager
    def _force(name: str):
        previous = display._state.profile
        display._state.profile = display._PROFILES[name]
        try:
            yield display._state.profile
        finally:
            display._state.profile = previous

    return _force


@pytest.fixture(autouse=True)
def reset_config_manager():
    """Reset ConfigManager's cached singleton before every test.

    ConfigManager._config is a class-level cache that persists across tests,
    causing ordering-dependent failures when one test writes a mode change
    that bleeds into the next.
    """
    from instrument_cluster.config import ConfigManager
    ConfigManager.reset()
    yield
    ConfigManager.reset()
