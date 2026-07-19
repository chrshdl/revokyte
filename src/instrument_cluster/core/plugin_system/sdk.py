import abc
from dataclasses import dataclass
from typing import Any

import pygame

from .plugin_layout import LayoutContext
from .plugin_bus_view import PluginBusView


@dataclass(frozen=True)
class SyncContext:
    """Inputs for a plugin's background sync pass (see
    ``GenericPlugin.background_sync``). Assembled by an extension's sync
    loop — the base build registers no sync hooks and never dispatches
    one. The cursor is whatever the previous ``SyncOutcome`` returned
    (opaque to the caller — e.g. an ETag)."""

    backend_url: str
    hardware_id: str
    auth_token: str
    cursor: object | None = None


@dataclass(frozen=True)
class SyncOutcome:
    """Result of one background sync pass.

    ok       — the backend answered; False lets the caller back off
               instead of retrying full-rate.
    changed  — local state changed; the caller requests a plugin reload.
    cursor   — passed back verbatim on the next pass.
    """

    ok: bool
    changed: bool
    cursor: object | None = None


class GenericPlugin(abc.ABC):
    """Base class for dashboard plugins.

    Class-attribute metadata (override in subclasses):
        plugin_id           — stable identifier; defaults to the module stem
                              at load time. An external plugin whose id
                              matches a packaged one shadows it.
        version             — semantic version string for logging/updates.
        required_feature    — feature key the plugin needs; the plugin is
                              skipped at load unless the manager's
                              feature_provider grants it. None = free.
        excluded_by_feature — inverse gate: the plugin is skipped while the
                              feature IS granted (e.g. the current-lap
                              widget yields its slot to the fuel pair).
        dashboard_only      — update() only runs while the dashboard is the
                              active state (hardware peripherals like the
                              shift-light LED bar).
        exclusive           — the plugin owns the whole screen: while an
                              exclusive plugin is granted and reports
                              ``provider_ready()``, every other WidgetPlugin
                              is suppressed (hardware plugins keep loading).

    Optional hooks an exclusive provider may implement:

    ``pages() -> list[str]`` / ``active_page() -> int`` /
    ``set_active_page(index)`` — the paging protocol the dashboard chrome
    duck-types against for its page dots, footer label, and swipe gesture.
    No pages (or no provider) means the single built-in view.

    ``@classmethod background_sync(cls, ctx: SyncContext) -> SyncOutcome``
    — periodic backend sync, dispatched by an extension for every
    feature-granted candidate class that defines it, independent of
    ``provider_ready()`` and of instantiation (so a provider whose local
    state hasn't arrived yet can still sync it into existence). Must be
    thread-safe with respect to the plugin's main-loop code. The base
    build never dispatches it.

    External plugins (loaded from ``/data/plugins``) may only import
    from the public ``instrument_cluster`` package and the stdlib; the
    surfaces they use — this SDK, ``ui/widgets`` and its registry, and
    the config module — are an informal API contract: renaming them
    breaks installed plugins.
    """

    plugin_id: str = ""
    version: str = "0.0.0"
    required_feature: str | None = None
    excluded_by_feature: str | None = None
    dashboard_only: bool = False
    exclusive: bool = False

    @classmethod
    def provider_ready(cls) -> bool:
        """Whether an ``exclusive`` plugin should take over the screen this
        load. Called by PluginManager during load_plugins(); must be cheap
        and never raise (the manager treats an exception as False). Not a
        load gate — an unready exclusive plugin still loads as an ordinary
        plugin."""
        return True

    def __init__(self, bus: PluginBusView, layout: LayoutContext | None = None) -> None:
        self.bus = bus
        self.layout = layout if layout is not None else LayoutContext.from_config()
        self.name = self.plugin_id or "Unknown Plugin"
        self.enabled = True

        self.sprites = pygame.sprite.Group()

    def get_signal(self, key: str, default: Any = 0.0) -> Any:
        """Get a value from the vehicle bus (frame attrs → signals → app_state)."""
        return self.bus.get_signal(key, default)

    @abc.abstractmethod
    def setup(self) -> None:
        """Create Labels/Sprites here and add them to self.sprites."""
        ...

    @abc.abstractmethod
    def update(self, dt: float) -> None:
        """Update values/positions of Sprites here."""
        ...

    def teardown(self) -> None:
        """Release everything setup() created. The default kills all
        sprites (removing them from every group, including the dashboard's
        draw layer); plugins owning hardware should override and reset it."""
        for sprite in list(self.sprites):
            sprite.kill()
        self.sprites.empty()

    def relayout(self, layout: LayoutContext) -> None:
        """Rebuild for a changed dashboard layout (status-lights toggle)."""
        self.teardown()
        self.layout = layout
        self.setup()


class WidgetPlugin(GenericPlugin):
    """Adapter base for the dashboard gauge widgets in ``ui/widgets``.

    Subclasses implement :meth:`build_widgets` returning widget sprites
    positioned via ``self.layout``; this base pumps each widget's
    ``update(bus, dt)`` from the plugin loop. The frame guard mirrors the
    dashboard's car-off behavior: gauges freeze while there is no
    telemetry (only system widgets keep updating).
    """

    system_widget = False

    @abc.abstractmethod
    def build_widgets(self) -> list:
        """Create and return the widget sprites at their layout rects."""
        ...

    def setup(self) -> None:
        self.widgets = self.build_widgets()
        self.sprites.add(*self.widgets)

    def update(self, dt: float) -> None:
        if self.bus.frame is None and not self.system_widget:
            return
        for widget in self.widgets:
            widget.update(self.bus, dt)
