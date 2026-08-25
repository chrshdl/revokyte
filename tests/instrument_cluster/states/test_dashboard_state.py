"""DashboardState: plugin linking/relinking and the dashboard-active gate."""

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pygame

from instrument_cluster.states.dashboard_state import DashboardState


@dataclass
class MockVehicleBus:
    frame: object = None
    signals: dict = field(default_factory=dict)
    app_state: dict = field(default_factory=dict)


class MockStateManager:
    def __init__(self):
        self.vehicle_bus = MockVehicleBus()
        self.change_state = MagicMock()
        self.push_state = MagicMock()


def make_plugin(sprite=None):
    plugin = MagicMock()
    plugin.sprites = pygame.sprite.Group(*([sprite] if sprite else []))
    return plugin


def make_manager(plugins=(), generation=1):
    pm = MagicMock()
    pm.plugins = list(plugins)
    pm.generation = generation
    return pm


def make_sprite():
    sprite = pygame.sprite.DirtySprite()
    sprite.image = pygame.Surface((1, 1))
    sprite.rect = sprite.image.get_rect()
    return sprite


def test_plugin_sprites_link_into_the_plugin_layer():
    sprite = make_sprite()
    pm = make_manager([make_plugin(sprite)])

    state = DashboardState(state_manager=MockStateManager(), plugin_manager=pm)
    # A state has no view until enter() borrows one from the ViewRegistry;
    # linking and the page dots moved there with it.
    state.pipeline = MagicMock()
    state.enter(pygame.Surface((1280, 720)))

    assert sprite in state.view.plugin_layer


def test_generation_change_relinks_new_sprites():
    pm = make_manager([], generation=1)
    state = DashboardState(state_manager=MockStateManager(), plugin_manager=pm)
    # A state has no view until enter() borrows one from the ViewRegistry;
    # linking and the page dots moved there with it.
    state.pipeline = MagicMock()
    state.enter(pygame.Surface((1280, 720)))

    # A reload replaced the plugin set (e.g. a feature grant added fuel).
    sprite = make_sprite()
    pm.plugins = [make_plugin(sprite)]
    pm.generation = 2

    state.update(0.016)

    assert sprite in state.view.plugin_layer


def test_dashboard_active_follows_the_state_lifecycle():
    pm = make_manager()
    state = DashboardState(state_manager=MockStateManager(), plugin_manager=pm)
    state.pipeline = MagicMock()

    state.enter(pygame.Surface((10, 10)))
    pm.set_dashboard_active.assert_called_with(True)

    state.on_pause()
    pm.set_dashboard_active.assert_called_with(False)

    state.on_resume()
    pm.set_dashboard_active.assert_called_with(True)

    state.exit()
    pm.set_dashboard_active.assert_called_with(False)


def test_status_lights_toggle_relayouts_plugins_before_view(monkeypatch):
    from instrument_cluster.config import ConfigManager

    pm = make_manager()
    state = DashboardState(state_manager=MockStateManager(), plugin_manager=pm)
    state.pipeline = MagicMock()
    state.enter(pygame.Surface((1280, 720)))

    calls = []
    pm.relayout.side_effect = lambda layout: calls.append(("plugins", layout))
    monkeypatch.setattr(
        state.view,
        "set_status_lights",
        lambda enabled: calls.append(("view", enabled)),
    )
    # Flip the toggle relative to whatever the view was built with. The view's
    # own reset() binds it too, so stub that out to keep this test about the
    # ordering the state guarantees: plugins reflow before the view does.
    monkeypatch.setattr(state.view, "reset", lambda ctx=None: None)
    flipped = not state.view.status_lights_enabled
    monkeypatch.setattr(
        ConfigManager, "get_config", lambda: MagicMock(status_lights=flipped)
    )

    state.on_resume()

    assert [c[0] for c in calls] == ["plugins", "view"]
    assert calls[0][1].status_lights is flipped


# --- page swipe + page dots (duck-typed against the provider) ---------------

import pytest

from instrument_cluster.config import ConfigManager
from instrument_cluster.states import dashboard_state as ds_mod


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path):
    """Pin the config — the dev machine's real config must not leak in."""
    ConfigManager.reset()
    ConfigManager.set_path(tmp_path / "config.json")
    yield
    ConfigManager.reset()


class FakeProvider:
    """Implements the exclusive provider's paging protocol in memory."""

    exclusive = True

    def __init__(self, names, active=0):
        self._names = list(names)
        self._active = active
        self.set_calls = []

    def pages(self):
        return list(self._names)

    def active_page(self):
        return self._active

    def set_active_page(self, index):
        self.set_calls.append(index)
        self._active = index


def make_paged_manager(provider, generation=1):
    pm = make_manager(generation=generation)
    pm.active_provider = lambda: provider
    return pm


def _finger(event_type, pos):
    return pygame.event.Event(
        event_type, {"x": pos[0] / 1280, "y": pos[1] / 720, "finger_id": 1}
    )


def _swipe(state, start, end):
    state.handle_event(_finger(pygame.FINGERDOWN, start))
    return state.handle_event(_finger(pygame.FINGERUP, end))


def make_state(pm=None):
    state = DashboardState(
        state_manager=MockStateManager(), plugin_manager=pm or make_manager()
    )
    # A state has no view until enter() borrows one from the ViewRegistry;
    # linking and the page dots moved there with it.
    state.pipeline = MagicMock()
    state.enter(pygame.Surface((1280, 720)))
    return state


def test_no_provider_hides_dots_and_ignores_swipes(isolated_environment):
    state = make_state(make_paged_manager(None))
    assert state.view.slot_dots.visible == 0

    assert _swipe(state, (900, 360), (300, 360)) is False


def _complete_slide(state, pm, surface):
    """Drive a pending slide to completion (snapshot -> reload -> anim)."""
    if state._slide is None:
        return
    state.draw(surface)          # snapshot + reload request
    pm.generation += 1           # the main loop executed the reload
    state.draw(surface)          # anim (zero duration in tests finishes it)


def test_swipe_cycles_through_provider_pages(isolated_environment, monkeypatch):
    monkeypatch.setattr(ds_mod, "SLIDE_DURATION_S", 0.0)
    provider = FakeProvider(["DEFAULT", "Race"])
    pm = make_paged_manager(provider)
    surface = pygame.Surface((1280, 720))

    state = make_state(pm)
    assert state.view.slot_dots.visible == 1
    assert state.view.slot_dots._count == 2
    assert state.view.slot_dots._active == 0

    # Swipe left: page 0 -> 1, then the edge holds.
    assert _swipe(state, (900, 360), (300, 360)) is True
    assert provider.set_calls == [1]
    _complete_slide(state, pm, surface)
    assert pm.request_reload.call_count == 1
    assert state.view.slot_dots._active == 1

    assert _swipe(state, (900, 360), (300, 360)) is True  # consumed, no change
    assert provider.set_calls == [1]
    assert pm.request_reload.call_count == 1

    # Swipe right goes back to the first page.
    assert _swipe(state, (300, 360), (900, 360)) is True
    assert provider.set_calls == [1, 0]
    _complete_slide(state, pm, surface)
    assert pm.request_reload.call_count == 2
    assert state.view.slot_dots._active == 0


def test_empty_provider_pages_produce_no_dots(isolated_environment):
    # Provider loaded but nothing synced yet: single page, no dots.
    state = make_state(make_paged_manager(FakeProvider([])))
    assert state.view.slot_dots.visible == 0


def test_slot_name_label_hidden_without_pages(isolated_environment):
    # No provider: the built-in default carries no label.
    state = make_state(make_paged_manager(None))
    assert state.view.slot_name.visible == 0
    assert state.view.slot_name._last_value_str == ""


def test_slot_name_label_tracks_the_active_page(isolated_environment, monkeypatch):
    monkeypatch.setattr(ds_mod, "SLIDE_DURATION_S", 0.0)
    provider = FakeProvider(["DEFAULT", "Wet"])
    pm = make_paged_manager(provider)
    surface = pygame.Surface((1280, 720))

    state = make_state(pm)
    assert state.view.slot_name._last_value_str == "DEFAULT"
    assert state.view.slot_name.visible == 1

    assert _swipe(state, (900, 360), (300, 360)) is True  # -> page 1
    _complete_slide(state, pm, surface)
    assert state.view.slot_name._last_value_str == "Wet"


def test_provider_errors_fall_back_to_single_page(isolated_environment):
    class BrokenProvider:
        def pages(self):
            raise RuntimeError("boom")

    state = make_state(make_paged_manager(BrokenProvider()))
    assert state.view.slot_dots.visible == 0
    assert _swipe(state, (900, 360), (300, 360)) is False


def test_taps_and_vertical_drags_are_not_swipes(isolated_environment):
    provider = FakeProvider(["DEFAULT", "Race"])
    state = make_state(make_paged_manager(provider))

    assert _swipe(state, (640, 360), (660, 360)) is False  # tap-ish
    assert _swipe(state, (900, 100), (300, 600)) is False  # too diagonal
    assert provider.set_calls == []


def test_swipe_slides_between_pages(isolated_environment, monkeypatch):
    provider = FakeProvider(["DEFAULT", "Race"])
    pm = make_paged_manager(provider, generation=1)
    state = make_state(pm)
    surface = pygame.Surface((1280, 720))
    now = [0.0]
    monkeypatch.setattr(ds_mod.time, "monotonic", lambda: now[0])

    # Swipe left advances to the second page.
    assert _swipe(state, (900, 360), (300, 360)) is True
    assert provider.set_calls == [1]
    assert pm.request_reload.call_count == 0  # deferred until snapshot

    # snapshot phase: old frame captured, reload requested, nothing drawn
    assert state.draw(surface) == []
    assert pm.request_reload.call_count == 1

    # reload hasn't executed yet: hold the old frame
    assert state.draw(surface) == []

    # a new gesture mid-slide is ignored entirely
    assert _swipe(state, (300, 360), (900, 360)) is False
    assert provider.set_calls == [1]

    # the main loop executed the reload -> animation runs full-screen
    pm.generation = 2
    assert state.draw(surface) == [surface.get_rect()]
    assert state._slide is not None

    # past the duration: final frame, then normal drawing resumes
    now[0] = 1.0
    assert state.draw(surface) == [surface.get_rect()]
    assert state._slide is None


# --- notification popup window opt-in ----------------------------------------


def test_dashboard_opts_into_notification_popups(isolated_environment):
    """The NOTIFICATION-layer popup window only shows over states that
    opt in — the dashboard does (extension popups duck-type the flag)."""
    assert make_state().allows_notification_popup is True


def test_pause_cancels_a_running_slide(isolated_environment):
    provider = FakeProvider(["DEFAULT", "Race"])
    state = make_state(make_paged_manager(provider, generation=1))
    surface = pygame.Surface((1280, 720))

    _swipe(state, (900, 360), (300, 360))
    state.draw(surface)  # snapshot -> wait
    state.on_pause()
    assert state._slide is None
