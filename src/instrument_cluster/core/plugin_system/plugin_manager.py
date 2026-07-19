"""Plugin discovery, feature gating, and lifecycle.

Two plugin sources:

* the **packaged** directory (``instrument_cluster/plugins``) shipped in
  the OS image — every gauge — imported as regular
  package modules (``.py`` or ``.pyc``);
* the **external** directory on the writable data partition
  (``/data/plugins/<slug>/`` on the Pi, ``~/.instrument-cluster/plugins``
  in development) — loaded from file, so no rootfs change is needed.

An external plugin whose ``plugin_id`` matches a packaged one shadows it,
which allows dropping in a widget fix without an OS update.

Feature gating is pluggable: a plugin class declaring ``required_feature``
is simply not instantiated unless the manager's ``feature_provider`` grants
that feature (``excluded_by_feature`` is the inverse). The default grants
nothing — every shipped plugin is free and declares no feature; an
extension may install its own provider before plugins load. Files stay
on disk either way — a feature change is a reload, not a reinstall.
"""

import importlib
import importlib.util
import inspect
import os
import platform
import threading
from pathlib import Path

from ...logger import Logger
from .plugin_bus_view import PluginBusView
from .plugin_layout import LayoutContext
from .sdk import GenericPlugin, WidgetPlugin

if platform.system() == "Darwin":
    EXTERNAL_PLUGIN_DIR = Path.home() / ".instrument-cluster" / "plugins"
else:
    EXTERNAL_PLUGIN_DIR = Path("/data/plugins")


class NullFeatureProvider:
    """Default: no optional feature is granted, and there is no cached
    state to invalidate. An extension may replace this (from its wire
    hook) before plugins load."""

    def has_feature(self, key: str) -> bool:
        return False

    def invalidate(self) -> None:
        pass


class PluginManager:
    def __init__(self, plugin_dir, vehicle_bus, external_dir=None):
        self.plugin_dir = plugin_dir
        self.external_dir = Path(external_dir) if external_dir else EXTERNAL_PLUGIN_DIR
        self.vehicle_bus = vehicle_bus
        # Grants (or denies) the feature keys plugin classes declare via
        # required_feature. Swappable so an extension can wire in its own
        # check without this package knowing what backs it.
        self.feature_provider = NullFeatureProvider()
        # Plugin classes registered directly (extensions contribute
        # classes here from wire(), before load_plugins runs). They rank
        # between packaged and external: an external file can still
        # shadow one by plugin_id for a hot fix.
        self.contributed_classes: list[type[GenericPlugin]] = []
        self.plugins: list[GenericPlugin] = []
        # Feature-granted candidate classes exposing a background_sync
        # hook — collected on every load, independent of instantiation, so
        # an extension's sync loop can sync a provider's data into
        # existence even before the provider is ready to take the screen.
        # With no extension installed the list is empty and nothing is
        # ever dispatched.
        self.sync_hooks: list[type[GenericPlugin]] = []
        # Bumped on every (re)load; the dashboard re-links plugin sprites
        # into its draw layer when it sees a generation it hasn't linked.
        self.generation = 0
        self._reload_requested = threading.Event()
        self._reload_invalidate_features = False
        self._dashboard_active = False
        self.logger = Logger(__class__.__name__).get()

    # --- loading -----------------------------------------------------------

    def load_plugins(self):
        """Scan both plugin directories and instantiate every eligible
        plugin class. External plugins shadow packaged ones by plugin_id."""
        candidates: dict[str, tuple[str, type]] = {}

        for plugin_id, cls in self._discover_packaged():
            candidates[plugin_id] = ("packaged", cls)
        for cls in self.contributed_classes:
            candidates[cls.plugin_id or cls.__name__] = ("contributed", cls)
        for plugin_id, cls in self._discover_external():
            if plugin_id in candidates:
                self.logger.info(
                    f"External plugin '{plugin_id}' shadows the "
                    f"{candidates[plugin_id][0]} one"
                )
            candidates[plugin_id] = ("external", cls)

        layout = LayoutContext.from_config()

        # Pass 1: the required_feature gate.
        eligible: dict[str, tuple[str, type]] = {}
        for plugin_id, (source, cls) in sorted(candidates.items()):
            if cls.required_feature and not self.feature_provider.has_feature(
                cls.required_feature
            ):
                self.logger.info(
                    f"Skipping plugin '{plugin_id}' "
                    f"(feature '{cls.required_feature}' not granted)"
                )
                continue
            eligible[plugin_id] = (source, cls)

        # Background-sync hooks are collected before the readiness check: a
        # provider whose local data hasn't synced yet is not ready, but its
        # sync hook is exactly what will make it ready.
        self.sync_hooks = [
            cls
            for _, cls in eligible.values()
            if callable(getattr(cls, "background_sync", None))
        ]

        # An exclusive provider replaces the standard gauge layout: while
        # an eligible exclusive plugin reports ready, every other
        # WidgetPlugin is suppressed (the provider decides what is on
        # screen) and hardware plugins keep loading. Any failure in this
        # chain — feature not granted, not ready, provider_ready() raising
        # — falls back to the standard dashboard.
        exclusive_id = None
        for plugin_id, (_, cls) in eligible.items():
            if not cls.exclusive:
                continue
            try:
                ready = bool(cls.provider_ready())
            except Exception as e:
                self.logger.warning(f"provider_ready() failed for '{plugin_id}': {e}")
                ready = False
            if not ready:
                continue
            if exclusive_id is None:
                exclusive_id = plugin_id
                self.logger.info(f"Exclusive dashboard provider: '{plugin_id}'")
            else:
                self.logger.warning(
                    f"Multiple ready exclusive providers; keeping "
                    f"'{exclusive_id}', ignoring '{plugin_id}'"
                )

        if exclusive_id is not None:
            for plugin_id, (_, cls) in list(eligible.items()):
                if issubclass(cls, WidgetPlugin) and plugin_id != exclusive_id:
                    self.logger.info(
                        f"Skipping plugin '{plugin_id}' (exclusive provider active)"
                    )
                    del eligible[plugin_id]

        # Pass 2: excluded_by_feature yields a slot only when some eligible
        # plugin actually provides that feature — a free device keeps the
        # free widget instead of showing an empty slot.
        provided = {
            cls.required_feature
            for _, cls in eligible.values()
            if cls.required_feature
        }

        loaded = []
        for plugin_id, (source, cls) in eligible.items():
            if cls.excluded_by_feature and cls.excluded_by_feature in provided:
                self.logger.info(
                    f"Skipping plugin '{plugin_id}' "
                    f"(slot taken by '{cls.excluded_by_feature}')"
                )
                continue
            try:
                plugin = self._instantiate(cls, layout)
                plugin.setup()
                loaded.append(plugin)
                self.logger.info(
                    f"Loaded plugin: {plugin.name} v{plugin.version} ({source})"
                )
            except Exception as e:
                self.logger.warning(f"Failed to load plugin '{plugin_id}': {e}")

        self.plugins = loaded
        self.generation += 1

    def _discover_packaged(self):
        """Yield (plugin_id, class) from the packaged plugins directory."""
        self.logger.info(f"Loading plugins from: {self.plugin_dir}")
        if not os.path.exists(self.plugin_dir):
            os.makedirs(self.plugin_dir)

        for filename in sorted(os.listdir(self.plugin_dir)):
            if not filename.endswith((".py", ".pyc")) or filename.startswith("__"):
                continue
            module_name = f"instrument_cluster.plugins.{Path(filename).stem}"
            try:
                module = importlib.import_module(module_name)
            except Exception as e:
                self.logger.warning(f"Failed to import plugin {filename}: {e}")
                continue
            yield from self._classes_in(module, Path(filename).stem)

    def _discover_external(self):
        """Yield (plugin_id, class) from the writable plugin directory.

        Layout: one subdirectory per installed plugin (``<slug>/<slug>.py``,
        falling back to the first ``*.py``); loose ``*.py`` files directly
        in the directory also load, which is handy in development.
        """
        root = self.external_dir
        if not root.is_dir():
            return

        entries = []
        for path in sorted(root.iterdir()):
            if path.is_dir() and not path.name.startswith(("_", ".")):
                preferred = path / f"{path.name}.py"
                if preferred.is_file():
                    entries.append((path.name, preferred))
                else:
                    loose = sorted(
                        p
                        for p in path.glob("*.py")
                        if not p.name.startswith("_")
                    )
                    if loose:
                        entries.append((path.name, loose[0]))
            elif path.suffix == ".py" and not path.name.startswith(("_", ".")):
                entries.append((path.stem, path))

        for slug, file_path in entries:
            try:
                module = self._load_module_from_file(slug, file_path)
            except Exception as e:
                self.logger.warning(f"Failed to load external plugin {slug}: {e}")
                continue
            yield from self._classes_in(module, slug)

    @staticmethod
    def _load_module_from_file(slug: str, file_path: Path):
        """Execute a plugin file as a throwaway module.

        Compiles the source directly instead of going through the import
        machinery: no stale __pycache__ (a reinstalled plugin takes effect
        on the next reload) and no bytecode writes into /data.
        """
        import types

        module_name = f"ic_external_plugins.{slug}"
        module = types.ModuleType(module_name)
        module.__file__ = str(file_path)
        code = compile(file_path.read_text(), str(file_path), "exec")
        exec(code, module.__dict__)
        return module

    def _classes_in(self, module, default_id: str):
        for _, obj in inspect.getmembers(module):
            if (
                inspect.isclass(obj)
                and issubclass(obj, GenericPlugin)
                and not inspect.isabstract(obj)
                and obj.__module__ == module.__name__
            ):
                yield (obj.plugin_id or default_id), obj

    def _instantiate(self, cls, layout: LayoutContext) -> GenericPlugin:
        bus_view = PluginBusView(self.vehicle_bus)
        try:
            return cls(bus_view, layout)
        except TypeError:
            # Pre-layout plugin signature: __init__(self, bus).
            return cls(bus_view)

    # --- reload ------------------------------------------------------------

    def active_provider(self) -> GenericPlugin | None:
        """The loaded exclusive dashboard provider, if one took the screen
        this load. The dashboard chrome duck-types its paging protocol
        (pages/active_page/set_active_page) against this instance."""
        for plugin in self.plugins:
            if plugin.exclusive:
                return plugin
        return None

    def request_reload(self, invalidate_features: bool = True) -> None:
        """Thread-safe: ask the main loop to reload plugins. Feature
        grants may change on background threads, but pygame surfaces must
        be created on the main thread.

        ``invalidate_features=False`` skips ``feature_provider.invalidate()``
        on the reload: a dashboard slot switch changes no feature state,
        and a provider's invalidate may be expensive (e.g. re-reading an
        encrypted store) and would stall the swipe. Requests merge: if
        any requester needs invalidation, it happens.
        """
        if invalidate_features:
            self._reload_invalidate_features = True
        self._reload_requested.set()

    def consume_reload_request(self) -> bool:
        if self._reload_requested.is_set():
            self._reload_requested.clear()
            return True
        return False

    def reload_plugins(self) -> None:
        """Tear down every plugin and rescan both directories against the
        current feature grants. Main thread only."""
        self.logger.info("Reloading plugins")
        for plugin in self.plugins:
            try:
                plugin.teardown()
            except Exception as e:
                self.logger.warning(f"Plugin teardown failed ({plugin.name}): {e}")
        self.plugins = []
        # The feature provider's backing state may have changed — unless
        # every requester said otherwise (slot switches).
        if self._reload_invalidate_features:
            self.feature_provider.invalidate()
        self._reload_invalidate_features = False
        self.load_plugins()

    def relayout(self, layout: LayoutContext) -> None:
        """Rebuild plugin sprites for a changed dashboard layout."""
        for plugin in self.plugins:
            try:
                plugin.relayout(layout)
            except Exception as e:
                self.logger.warning(f"Plugin relayout failed ({plugin.name}): {e}")
        self.generation += 1

    # --- per-frame ---------------------------------------------------------

    def set_dashboard_active(self, active: bool) -> None:
        """Gates dashboard_only plugins (hardware peripherals) so they only
        run while the dashboard is the top state — matching the old
        DashboardState.peripherals cadence."""
        self._dashboard_active = active

    def update(self, dt):
        for plugin in self.plugins:
            if not plugin.enabled:
                continue
            if plugin.dashboard_only and not self._dashboard_active:
                continue
            try:
                plugin.update(dt)
            except Exception as e:
                # One faulty plugin must not take down the 60 fps loop.
                plugin.enabled = False
                self.logger.error(
                    f"Plugin '{plugin.name}' crashed and was disabled: {e}"
                )
