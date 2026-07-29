"""Add-on discovery: installed distributions may extend the cluster.

The base build is complete without any extension. At startup,
:meth:`ExtensionRuntime.load` looks up the ``instrument_cluster.extensions``
entry-point group and calls every registered hook::

    # in the extension distribution's pyproject.toml
    [project.entry-points."instrument_cluster.extensions"]
    my_extension = "my_package:wire"

    # in my_package
    def wire(runtime: ExtensionRuntime) -> None: ...

``wire`` runs once, after the core objects exist but *before* plugins
load, so it may install a feature provider on ``runtime.plugin_manager``
or append to its ``contributed_classes`` first. Inside ``wire`` an
extension registers what it needs:

* ``runtime.add_signal_processor(p)`` — ``p.update() -> dict`` is polled
  every frame from the main loop and merged into ``bus.signals``;
  ``p.stop()`` runs at shutdown.
* ``runtime.add_setup_entry(SetupEntry(...))`` — an extra row in the
  Setup screen whose button switches to ``make_state(state_manager)``.
* Overlay windows go straight to ``runtime.window_manager.add_window``.
  A window shares the screen with whatever else is registered, so if it
  must be read alone it should set ``occludes_below`` (and if it must
  survive someone else's occlusion, ``show_when_occluded``) — see
  ui/window_layering.py. Note the cluster's own NO SIGNAL alert occludes,
  so an extension popup can be withdrawn while the link is dead and will
  come back on its own afterwards.

Extensions are fail-open: one that raises during ``wire`` has its
processor/entry registrations rolled back and is skipped (windows it
already added stay — the window manager is handed out directly), so a
broken extension degrades to the plain cluster instead of taking down
the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pygame

from .logger import Logger

ENTRY_POINT_GROUP = "instrument_cluster.extensions"


def _wire_hooks():
    """The registered (name, wire-callable) pairs. Separate function so
    tests can substitute their own without touching installed metadata."""
    from importlib.metadata import entry_points

    for ep in entry_points(group=ENTRY_POINT_GROUP):
        yield ep.name, ep.load()


@dataclass(frozen=True)
class SetupEntry:
    """An extra row an extension contributes to the Setup screen.

    The pygame event types are allocated once per entry at registration
    (never per view rebuild — the custom-type space is finite); SetupView
    builds the row button from them and SetupState switches to
    ``make_state(state_manager)`` on the released event.
    """

    icon: str  # material-symbols glyph for the row's icon cell
    label: str  # row caption
    # Text on the row's action button; a callable is re-evaluated on every
    # Setup entry (the view is rebuilt each time), so the label can track
    # whatever state the extension exposes.
    button_text: str | Callable[[], str]
    make_state: Callable[[Any], Any]  # state_manager -> State
    pressed: int = field(default_factory=pygame.event.custom_type)
    released: int = field(default_factory=pygame.event.custom_type)


class ExtensionRuntime:
    """Registry extensions wire themselves into (see module docstring).

    A module-level singleton (``extensions.runtime``) rather than a
    constructor argument threaded through every state: the Setup screen
    is rebuilt on every entry and only needs to *read* the registered
    entries.
    """

    def __init__(self):
        self.logger = Logger(__class__.__name__).get()
        self.loaded: list[str] = []
        self.vehicle_bus = None
        self.state_manager = None
        self.window_manager = None
        self.plugin_manager = None
        self._signal_processors: list[Any] = []
        self.setup_entries: list[SetupEntry] = []

    @property
    def active(self) -> bool:
        return bool(self.loaded)

    # --- registration (called from an extension's wire()) ---

    def add_signal_processor(self, processor: Any) -> None:
        """``processor.update() -> dict`` merged into bus.signals every
        frame; ``processor.stop()`` (optional) called at shutdown."""
        self._signal_processors.append(processor)

    def add_setup_entry(self, entry: SetupEntry) -> None:
        self.setup_entries.append(entry)

    # --- lifecycle (called from main) ---

    def load(self, *, vehicle_bus, state_manager, window_manager, plugin_manager):
        """Discover and wire every registered extension.

        No installed extensions (the base image) is the normal case and
        silent. A *broken* extension is logged and its registrations are
        rolled back; the others keep their own."""
        self.vehicle_bus = vehicle_bus
        self.state_manager = state_manager
        self.window_manager = window_manager
        self.plugin_manager = plugin_manager

        try:
            hooks = list(_wire_hooks())
        except Exception as e:
            self.logger.error(f"Extension discovery failed: {e}")
            return

        for name, wire in hooks:
            processors_before = len(self._signal_processors)
            entries_before = len(self.setup_entries)
            try:
                wire(self)
                self.loaded.append(name)
                self.logger.info(f"Extension wired: {name}")
            except Exception as e:
                self.logger.error(f"Extension '{name}' failed to wire: {e}")
                for processor in self._signal_processors[processors_before:]:
                    self._stop_processor(processor)
                del self._signal_processors[processors_before:]
                del self.setup_entries[entries_before:]

    def update_signals(self) -> dict:
        """Poll every registered processor; one crashing must not stall
        the 60 fps loop, so it is dropped after logging."""
        merged: dict = {}
        for processor in list(self._signal_processors):
            try:
                merged.update(processor.update() or {})
            except Exception as e:
                self._signal_processors.remove(processor)
                self.logger.error(f"Extension processor removed after crash: {e}")
        return merged

    def stop(self) -> None:
        for processor in self._signal_processors:
            self._stop_processor(processor)

    def _stop_processor(self, processor: Any) -> None:
        stop = getattr(processor, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception as e:
                self.logger.warning(f"Extension processor stop failed: {e}")


runtime = ExtensionRuntime()
