"""Renders the cluster's real views offscreen for the editor canvas.

Every builder constructs the genuine view/widget objects — the canvas is
WYSIWYG because it *is* the app's rendering, not a mock-up. Views read
``active_skin()`` at construction, so an edit means: register the working
skin as the override, force the matching display profile, and rebuild the
view object from scratch. The surface handed back is the panel's native
logical size; the canvas scales it to fit.
"""

from __future__ import annotations

import os
import tempfile

import pygame

import instrument_cluster
from instrument_cluster.core.plugin_system.plugin_layout import LayoutContext
from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus
from instrument_cluster.peripherals import display
from instrument_cluster.ui.colors import Color

from . import demo_data

#: skin size → display profile name (the profile carries the logical size
#: the skin targets; forcing it is what makes active_skin() resolve).
PROFILE_FOR_SIZE = {
    (1280, 720): "dev",
    (1024, 600): "waveshare_7",
    (800, 480): "waveshare_5",
}

VIEWS = [
    ("dashboard", "Dashboard"),
    ("dashboard_lights", "Dashboard + status lights"),
    ("overlays", "Dashboard + overlays"),
    ("setup", "Setup"),
    ("wifi_scan", "Wi-Fi scan"),
    ("wifi_password", "Wi-Fi password"),
    ("wifi_manual", "Wi-Fi manual entry"),
    ("enter_ip", "Enter IP"),
    ("install", "Install feed"),
    ("agent", "Agent setup"),
]


def force_profile_for(size: tuple[int, int]) -> None:
    name = PROFILE_FOR_SIZE[tuple(size)]
    display._state.profile = display._PROFILES[name]


_manager = None
_manager_bus: VehicleBus | None = None


def _plugin_manager():
    """The editor's PluginManager — real discovery over the packaged
    plugin directory, exactly like the app, so a newly added gauge plugin
    shows up in the canvas with no editor change.

    Built once per process. The external plugin directory is pointed at an
    empty temp dir so stray plugins on the designer's machine can't shadow
    packaged gauges — the editor's canvas must show what ships. Non-widget
    plugins (shift-lights drives the Blinkt LED bar and paints nothing) are
    torn down and dropped after load: keeping them would re-construct
    hardware controllers on every relayout-driven rebuild.
    """
    global _manager, _manager_bus
    if _manager is None:
        from instrument_cluster.core.plugin_system.plugin_manager import (
            PluginManager,
        )
        from instrument_cluster.core.plugin_system.sdk import WidgetPlugin

        _manager_bus = VehicleBus()
        _manager_bus.frame = demo_data.demo_frame()
        _manager_bus.signals.update(demo_data.FAKE_SIGNALS)
        packaged = os.path.join(
            os.path.dirname(instrument_cluster.__file__), "plugins"
        )
        _manager = PluginManager(
            packaged,
            _manager_bus,
            external_dir=tempfile.mkdtemp(prefix="skin_editor_ext_"),
        )
        _manager.load_plugins()
        visual, hardware = [], []
        for plugin in _manager.plugins:
            (visual if isinstance(plugin, WidgetPlugin) else hardware).append(
                plugin
            )
        for plugin in hardware:
            plugin.teardown()
        _manager.plugins = visual
    return _manager


def _render_dashboard(surface: pygame.Surface, lights: bool) -> None:
    from instrument_cluster.ui.views.dashboard_view import DashboardView

    # The view owns the chrome; gauge sprites link into its plugin layer,
    # exactly as DashboardState does at runtime.
    view = DashboardView()
    view.status_lights_enabled = lights
    view._apply_shifts()
    if lights:
        view.widget_layer.empty()
        view._init_widgets()

    # Three LayeredDirty groups share one surface: force dirty-rect mode so
    # no group's *first* draw blits its background across the whole surface
    # over the previous groups' work (the same trap SetupView documents).
    for layer in (view.widget_layer, view.plugin_layer, view.ui_layer):
        layer._use_update = True

    # relayout() is the app's own rebuild path (teardown + build_widgets):
    # widgets re-read active_skin(), which is how every edit shows up.
    manager = _plugin_manager()
    manager.relayout(LayoutContext(status_lights=lights))
    manager.update(0.016)
    for plugin in manager.plugins:
        for sprite in plugin.sprites:
            view.plugin_layer.add(sprite)

    background = pygame.Surface(surface.get_size())
    background.fill(Color.BLACK.rgb())
    surface.blit(background, (0, 0))
    view.full_paint(surface, background)


def _render_overlays(surface: pygame.Surface) -> None:
    from instrument_cluster.ui import no_signal_window
    from instrument_cluster.ui.wifi_status_window import _build_pill

    _render_dashboard(surface, lights=False)
    # Knock the base back the way FeedUpdateWindow's dimming does, then
    # composite the two passive overlays where their windows place them.
    dim = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    dim.fill((0, 0, 0, 90))
    surface.blit(dim, (0, 0))

    rect = no_signal_window.banner_rect()
    surface.blit(no_signal_window.build_banner(rect.size), rect)

    pill = _build_pill()
    surface.blit(pill.image, pill.rect)


def _render_setup(surface: pygame.Surface) -> None:
    from instrument_cluster.ui.views.setup_view import SetupView

    view = SetupView()
    background = pygame.Surface(surface.get_size())
    background.fill(Color.BLACK.rgb())
    view.draw_static_elements(background)
    view.full_paint(surface, background)


def _render_enter_ip(surface: pygame.Surface) -> None:
    from instrument_cluster.ui.views.enter_ip_view import EnterIPView

    view = EnterIPView(recent_connected=demo_data.FAKE_RECENT_IPS)
    background = pygame.Surface(surface.get_size())
    background.fill(Color.BLACK.rgb())
    view.draw_static_elements(background)
    view.full_paint(surface, background)


def _fake_networks():
    from instrument_cluster.core.system.wifi_manager import Network

    return [
        Network(ssid=ssid, secured=secured, signal_dbm=dbm)
        for ssid, secured, dbm in demo_data.FAKE_NETWORKS
    ]


def _render_wifi(surface: pygame.Surface, phase: str) -> None:
    from instrument_cluster.ui.views.wifi_setup_view import WifiSetupView

    view = WifiSetupView()
    if phase == "scan":
        view.show_networks(_fake_networks(), demo_data.FAKE_CURRENT_SSID)
    elif phase == "password":
        view.show_password("Home Network", secured=True, manual=False)
    else:  # manual
        view.show_password(None, secured=True, manual=True)
    view.full_paint(surface, None)


def _render_install(surface: pygame.Surface) -> None:
    from instrument_cluster.ui.views.install_view import InstallView

    view = InstallView(feed_label="Gran Turismo 7")
    view.set_status("Downloading  telemetry  bundle ...")
    background = pygame.Surface(surface.get_size())
    background.fill(Color.BLACK.rgb())
    view.draw_static_elements(background)
    view.full_paint(surface, background)


def _render_agent(surface: pygame.Surface) -> None:
    from instrument_cluster.ui.views.agent_setup_view import AgentSetupView

    view = AgentSetupView(feed_label="the network feed")
    view.url_label.set_text("http://192.168.1.30:8321")
    background = pygame.Surface(surface.get_size())
    background.fill(Color.BLACK.rgb())
    view.draw_static_elements(background)
    view.full_paint(surface, background)


class ViewHost:
    """Owns the offscreen surface and rebuilds it on demand."""

    def __init__(self):
        self.view_id = "dashboard"
        self.surface: pygame.Surface | None = None
        self.error: str | None = None

    def render(self, skin) -> pygame.Surface:
        """(Re)build the current view for ``skin`` and return the surface."""
        force_profile_for(skin.size)
        self.surface = pygame.Surface(skin.size)
        self.surface.fill(Color.BLACK.rgb())
        self.error = None
        try:
            if self.view_id == "dashboard":
                _render_dashboard(self.surface, lights=False)
            elif self.view_id == "dashboard_lights":
                _render_dashboard(self.surface, lights=True)
            elif self.view_id == "overlays":
                _render_overlays(self.surface)
            elif self.view_id == "setup":
                _render_setup(self.surface)
            elif self.view_id == "wifi_scan":
                _render_wifi(self.surface, "scan")
            elif self.view_id == "wifi_password":
                _render_wifi(self.surface, "password")
            elif self.view_id == "wifi_manual":
                _render_wifi(self.surface, "manual")
            elif self.view_id == "enter_ip":
                _render_enter_ip(self.surface)
            elif self.view_id == "install":
                _render_install(self.surface)
            elif self.view_id == "agent":
                _render_agent(self.surface)
        except Exception as exc:  # never take the editor down with a view
            self.error = f"{type(exc).__name__}: {exc}"
            self.surface.fill((25, 8, 8))
        return self.surface
