"""FeedUpdateWindow — the once-per-boot stale-feed notice."""
import pygame
import pytest

from instrument_cluster.config import Config
from instrument_cluster.ui.feed_update_window import (
    DIM_PERCENT,
    FeedUpdateWindow,
    body_lines,
)
from instrument_cluster.ui.widgets.base.modal_dimming import ModalDimming
from instrument_cluster.ui.window_layering import WindowLayer

SCREEN = (1280, 720)


class _DashboardState:
    allows_notification_popup = True


class _PlainState:
    """Setup, IP entry, install, wifi — none opt in."""


class _StateManager:
    def __init__(self, state=None):
        self.current_state = state or _DashboardState()


def _config(**overrides):
    values = {
        "telemetry_mode": "udp",
        "telemetry_feed": "granturismo",
        "telemetry_feed_version": "v0.3.10",
    }
    values.update(overrides)
    return Config(**values)


def _window(config=None, state=None):
    return FeedUpdateWindow(config or _config(), _StateManager(state), SCREEN)


# --- When it appears -------------------------------------------------------


def test_shown_when_the_installed_feed_is_stale():
    assert _window().visible is True


def test_hidden_when_the_installed_feed_matches_the_pin():
    from instrument_cluster.addons.feeds import feed_by_id

    pinned = feed_by_id("granturismo").version
    assert _window(_config(telemetry_feed_version=pinned)).visible is False


def test_hidden_in_demo_mode():
    """Demo runs no installed feed, so nothing can be stale."""
    assert _window(_config(telemetry_mode="demo")).visible is False


def test_hidden_when_no_feed_is_installed():
    assert _window(_config(telemetry_feed="", telemetry_feed_version="")).visible is False


def test_shown_when_the_installed_version_is_unknown():
    assert _window(_config(telemetry_feed_version="")).visible is True


def test_hidden_on_states_that_do_not_opt_in():
    assert _window(state=_PlainState()).visible is False


def test_sits_below_the_system_alert_layer():
    """A stale feed is a notice; a dead link is an alert."""
    win = _window()
    assert win.layer is WindowLayer.NOTIFICATION
    assert win.layer < WindowLayer.SYSTEM_ALERT


# --- Acting on it ----------------------------------------------------------


def _tap(win, button):
    """Press and release a button, then pump what it posted back through.

    Touch rather than mouse: Display.to_logical divides mouse coordinates by
    the display surface, which the test harness sets to 1x1, so mouse
    positions land nowhere. Finger events carry normalized coordinates and
    are what the panel actually sends.

    Buttons post their action event to the pygame queue, so in the app it
    arrives on the next frame — the tests route it the same way.
    """
    pygame.event.clear()
    cx, cy = button.rect.center
    payload = {"x": cx / SCREEN[0], "y": cy / SCREEN[1], "finger_id": 1}
    for kind in (pygame.FINGERDOWN, pygame.FINGERUP):
        win.handle_event(pygame.event.Event(kind, payload))
    for posted in pygame.event.get():
        win.handle_event(posted)


def test_stays_dismissed_for_the_rest_of_the_boot():
    """Once per boot: it must not come back when the dashboard resumes."""
    win = _window()
    win.dismiss()

    win._state_manager.current_state = _PlainState()
    win._state_manager.current_state = _DashboardState()

    assert win.visible is False


class _FakeInstall:
    """Stands in for InstallState, recording how it was constructed."""

    last = {}

    def __init__(self, sm, descriptor=None, ip="", auto_start=False):
        _FakeInstall.last = {
            "descriptor": descriptor,
            "ip": ip,
            "auto_start": auto_start,
        }


def _patch_install(monkeypatch, cfg, env_ip=""):
    from instrument_cluster.addons import installer
    from instrument_cluster.config import ConfigManager
    from instrument_cluster.states import install_state as install_module
    from instrument_cluster.ui import feed_update_window

    monkeypatch.setattr(ConfigManager, "get_config", classmethod(lambda cls: cfg))
    monkeypatch.setattr(install_module, "InstallState", _FakeInstall)
    monkeypatch.setattr(installer, "installed_feed_ip", lambda: env_ip)
    return feed_update_window


def test_update_now_asks_for_nothing(monkeypatch):
    """No retyping an address the machine is already using, and no second
    Install press to confirm a choice already made."""
    pushed = []
    manager = _StateManager()
    manager.push_state = pushed.append

    cfg = _config()
    cfg.recent_connected = []
    _patch_install(monkeypatch, cfg, env_ip="192.168.1.50")

    win = FeedUpdateWindow(cfg, manager, SCREEN)
    win.start_update()

    assert len(pushed) == 1
    assert _FakeInstall.last["ip"] == "192.168.1.50"
    assert _FakeInstall.last["descriptor"].id == "granturismo"
    assert _FakeInstall.last["auto_start"] is True
    assert win.visible is False, "the notice gets out of the way"


def test_env_file_address_wins_over_the_last_typed_one(monkeypatch):
    """The env file is what the running proxy actually connects to;
    recent_connected is only what was last typed at a keypad."""
    manager = _StateManager()
    manager.push_state = lambda s: None

    cfg = _config()
    cfg.recent_connected = ["10.0.0.9"]
    _patch_install(monkeypatch, cfg, env_ip="192.168.1.50")

    FeedUpdateWindow(cfg, manager, SCREEN).start_update()

    assert _FakeInstall.last["ip"] == "192.168.1.50"


def test_falls_back_to_the_last_typed_address(monkeypatch):
    manager = _StateManager()
    manager.push_state = lambda s: None

    cfg = _config()
    cfg.recent_connected = ["10.0.0.9"]
    _patch_install(monkeypatch, cfg, env_ip="")

    FeedUpdateWindow(cfg, manager, SCREEN).start_update()

    assert _FakeInstall.last["ip"] == "10.0.0.9"


def test_update_now_asks_for_an_address_only_when_none_is_known(monkeypatch):
    """A device with no recoverable address — a feed installed before one was
    ever recorded — is the only case that still prompts."""
    from instrument_cluster.addons import installer
    from instrument_cluster.config import ConfigManager
    from instrument_cluster.states import enter_ip_state as enter_ip_module

    pushed = []
    manager = _StateManager()
    manager.push_state = pushed.append

    cfg = _config()
    cfg.recent_connected = []
    monkeypatch.setattr(ConfigManager, "get_config", classmethod(lambda cls: cfg))
    monkeypatch.setattr(installer, "installed_feed_ip", lambda: "")

    class _FakeEnterIP:
        def __init__(self, sm, descriptor=None, recent_connected=None):
            self.descriptor = descriptor

    monkeypatch.setattr(enter_ip_module, "EnterIPState", _FakeEnterIP)

    win = FeedUpdateWindow(cfg, manager, SCREEN)
    win.start_update()

    assert len(pushed) == 1
    assert isinstance(pushed[0], _FakeEnterIP)


def test_swallows_pointer_input_while_up():
    """Modal: a tap that missed the button must not reach the Setup button
    underneath, and must not dismiss either."""
    win = _window()
    miss = pygame.event.Event(
        pygame.FINGERUP, {"x": 0.05, "y": 0.9, "finger_id": 1}
    )

    assert win.handle_event(miss) is True
    assert win.visible is True, "the backdrop is not a way past the update"


def test_passes_events_through_once_dismissed():
    win = _window()
    win.dismiss()
    down = pygame.event.Event(
        pygame.FINGERDOWN, {"x": 0.05, "y": 0.9, "finger_id": 1}
    )

    assert win.handle_event(down) is False


# --- Appearance ------------------------------------------------------------


def test_dims_the_live_view_behind_the_card():
    win = _window()
    dimming = win.sprites[0]

    assert isinstance(dimming, ModalDimming)
    assert dimming.percent == DIM_PERCENT
    assert dimming.rect.size == SCREEN
    # Bottom of the stack: the card sits on top of it.
    assert win.sprites[-1].rect.size != SCREEN


def test_offers_only_updating():
    """No decline: a feed the image was never tested against is not a state
    to leave a device sitting in."""
    win = _window()
    assert not hasattr(win, "later_button")
    assert win.update_button in win.sprites
    # The button sits above the card, or it would be painted over.
    assert win.sprites.index(win.update_button) > win.sprites.index(win.sprites[1])


def test_tapping_the_button_starts_the_update(monkeypatch):
    from instrument_cluster.config import ConfigManager
    from instrument_cluster.states import install_state as install_module

    pushed = []
    manager = _StateManager()
    manager.push_state = pushed.append

    cfg = _config()
    cfg.recent_connected = ["192.168.1.50"]
    monkeypatch.setattr(ConfigManager, "get_config", classmethod(lambda cls: cfg))
    monkeypatch.setattr(install_module, "InstallState", lambda *a, **k: object())
    monkeypatch.setattr(
        __import__(
            "instrument_cluster.addons.installer", fromlist=["installed_feed_ip"]
        ),
        "installed_feed_ip",
        lambda: "192.168.1.50",
    )

    win = FeedUpdateWindow(cfg, manager, SCREEN)
    _tap(win, win.update_button)

    assert len(pushed) == 1


def test_card_names_both_builds():
    """Actionable, not merely alarming."""
    from instrument_cluster.addons.feeds import feed_by_id

    descriptor = feed_by_id("granturismo")
    text = " ".join(body_lines(descriptor, "v0.3.10"))

    assert "v0.3.10" in text
    assert descriptor.version in text
    assert descriptor.label in text


def test_card_says_unknown_rather_than_inventing_a_version():
    from instrument_cluster.addons.feeds import feed_by_id

    text = " ".join(body_lines(feed_by_id("granturismo"), ""))
    assert "unknown" in text.lower()


def test_card_text_stays_inside_the_card():
    """Regression: the dismiss hint overlapped the last body line."""
    from instrument_cluster.ui.feed_update_window import build_card
    from instrument_cluster.addons.feeds import feed_by_id

    card = build_card(feed_by_id("granturismo"), "v0.3.10")
    ink = card.get_bounding_rect()

    assert card.get_rect().contains(ink)


def test_dismissed_window_draws_nothing():
    win = _window()
    win.dismiss()
    surface = pygame.Surface(SCREEN)

    assert win.draw(surface, []) == []


def test_reappearing_redirties_its_sprites():
    """The card and dimming never change, so their sprites go clean after
    the first composite — without re-dirtying, a later show paints nothing.

    Reachable in the product because the window is constructed before the
    dashboard is pushed, so the very first show is a hidden -> visible
    transition.
    """
    manager = _StateManager(_PlainState())
    win = FeedUpdateWindow(_config(), manager, SCREEN)
    surface = pygame.Surface(SCREEN)

    win.update(0.016)
    assert win.visible is False
    win.draw(surface, [])

    for sprite in win.sprites:
        sprite.dirty = 0

    manager.current_state = _DashboardState()
    win.update(0.016)

    assert all(s.dirty == 1 for s in win.sprites)
    assert win.draw(surface, []), "must actually paint on the frame it appears"


def test_pressed_highlight_clears_on_release(monkeypatch):
    """Press, drag away, let go — the blue must not survive.

    A Button's idle image is transparent by default, and an overlay window
    has no background to restore under it (LayeredDirty.clear does that job
    in a normal view), so the stale pressed pixels showed through even once
    the state had cleared. The button paints the card colour to fix it.

    The highlight persisting *during* the drag is intended — see
    widgets/test_button_drag.py.
    """
    from instrument_cluster.ui.feed_update_window import _card_color
    from instrument_cluster.ui.widgets.base.button import ButtonState
    from instrument_cluster.ui.window_layering import WindowManager

    CARD_COLOR = _card_color()

    manager = _StateManager()
    manager.is_running = True
    manager.request_full_paint = lambda: None
    manager.draw = lambda surface: []
    manager.update = lambda dt: None

    win = _window()
    win._state_manager = manager
    wm = WindowManager(manager)
    wm.add_window(win)

    surface = pygame.Surface(SCREEN)
    button = win.update_button
    probe = button.rect.center

    def frame():
        wm.update(1 / 60)
        wm.draw(surface)

    frame()
    assert surface.get_at(probe)[:3] == CARD_COLOR

    wm.handle_event(_finger_at(pygame.FINGERDOWN, probe))
    frame()
    assert button.state is ButtonState.PRESSED
    assert surface.get_at(probe)[:3] != CARD_COLOR, "press should be visible"

    wm.handle_event(_finger_at(pygame.FINGERMOTION, (60, 700)))
    frame()
    assert button.state is ButtonState.PRESSED, "stays lit while held"

    wm.handle_event(_finger_at(pygame.FINGERUP, (60, 700)))
    frame()

    assert button.state is ButtonState.IDLE
    assert surface.get_at(probe)[:3] == CARD_COLOR, "highlight must be gone"


def _finger_at(kind, pos):
    x, y = pos
    return pygame.event.Event(
        kind, {"x": x / SCREEN[0], "y": y / SCREEN[1], "finger_id": 1}
    )
