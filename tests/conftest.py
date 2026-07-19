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
