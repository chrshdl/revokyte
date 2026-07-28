"""InstallState: the auto-start path used by the stale-feed notice."""
import pytest

from instrument_cluster.addons.feeds import feed_by_id
from instrument_cluster.states.install_state import InstallState


class _StateManager:
    is_running = True

    def request_full_paint(self):
        pass


@pytest.fixture
def screen():
    import pygame

    return pygame.Surface((1280, 720))


def test_waits_for_a_press_by_default(screen, monkeypatch):
    """First-time setup still confirms — the disclosure is the point."""
    started = []
    state = InstallState(_StateManager(), descriptor=feed_by_id("granturismo"), ip="1.2.3.4")
    monkeypatch.setattr(state, "_start_install", lambda: started.append(True))

    state.enter(screen)

    assert started == []


def test_auto_start_begins_without_a_press(screen, monkeypatch):
    """Invoked from the notice's Update now: the choice was already made, so
    asking again would be a second confirmation for one decision."""
    started = []
    state = InstallState(
        _StateManager(),
        descriptor=feed_by_id("granturismo"),
        ip="1.2.3.4",
        auto_start=True,
    )
    monkeypatch.setattr(state, "_start_install", lambda: started.append(True))

    state.enter(screen)

    assert started == [True]


def test_auto_start_says_it_is_updating(screen):
    state = InstallState(
        _StateManager(),
        descriptor=feed_by_id("granturismo"),
        ip="1.2.3.4",
        auto_start=True,
    )
    text = " ".join(lbl.text for lbl in state.view.info_labels)

    assert "Press Install" not in text
    assert "Cancel" in text, "there is still a way out"
