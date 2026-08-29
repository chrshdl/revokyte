import os
import time

import pygame

from ..peripherals.backlight import Backlight
from ..peripherals.display import active_profile
from ..config import ConfigManager
from ..core.plugin_system.plugin_layout import LayoutContext
from ..debug.debug_sender import DebugSender
from ..logger import Logger
from ..signals.signal_pipeline import SignalPipeline
from ..states.setup_state import SetupState
from ..states.state import State
from ..states.state_manager import StateManager
from ..ui.events import (
    BUTTON_SETUP_LONGPRESSED,
    BUTTON_SETUP_RELEASED,
)
from ..ui.skins import active_skin
from ..ui.views.dashboard_view import DashboardView

# A slot swipe must travel far enough horizontally to never collide with
# button taps, and stay flat enough to not be a scroll-ish gesture. The
# thresholds are per-skin (native px): swipe positions arrive in logical
# coordinates, so a fixed design-px threshold made the gesture ~1.6x
# harder on the 800x480 panel.

# Slide transition between dashboard pages (ease-out cubic).
SLIDE_DURATION_S = 0.26


class DashboardState(State):
    """The main racing view — a pure consumer of the bus.

    All gauges (and the shift-light LED peripheral) are plugins owned by
    the PluginManager; this state links their sprites into the view's
    plugin_layer and re-links whenever the manager's generation changes
    (plugin reload after a feature-grant change) or the layout reflows.
    """

    # Opt-in for NOTIFICATION-layer popup windows (duck-typed by
    # extension-contributed popups): they may only appear while this
    # state is active. Harmless with no popups registered.
    allows_notification_popup = True

    # Opt-in for SYSTEM_ALERT overlays (the NO SIGNAL banner). Set here and
    # nowhere else: Setup is where a dead feed gets configured, so covering
    # it with the alert would obscure the remedy.
    allows_system_alert = True

    view_class = DashboardView

    def __init__(
        self,
        state_manager: StateManager = None,
        pipeline: SignalPipeline | None = None,
        plugin_manager=None,
    ):
        super().__init__(state_manager)

        self.logger = Logger(__class__.__name__).get()
        self.bus = state_manager.vehicle_bus
        self.pipeline = pipeline or SignalPipeline()

        self.plugin_manager = plugin_manager or getattr(
            state_manager, "plugin_manager", None
        )
        self._linked_generation = -1
        # Which status-lights layout the gauge plugins were last BUILT with.
        # Tracked here rather than read back off the view: DashboardView.reset()
        # binds the view's own flag from config on every entry and resume, so
        # the view can never tell us what the plugins are still holding.
        self._plugin_lights: bool | None = None

        debug_dest_ip = os.environ.get("DEBUG_DEST_IP", "")
        if debug_dest_ip:
            self.debug_sender = DebugSender(
                delta_signal=self.pipeline.delta,
                dest_ip=debug_dest_ip,
                port=int(os.environ.get("DEBUG_PORT", "5005")),
            )
        else:
            self.debug_sender = None

        self._swipe_start: tuple[int, int] | None = None
        # Slide transition state machine (see draw()): None, or a dict
        # walking snapshot -> wait (reload) -> anim.
        self._slide: dict | None = None

    @property
    def plugins(self) -> list:
        return list(self.plugin_manager.plugins) if self.plugin_manager else []

    def _link_plugins(self) -> None:
        """Make the view's plugin layer hold exactly the current plugins.

        Idempotent per view and safe to call again after a reload or view
        rebuild; a sprite may live in several groups, and killed sprites
        (from a plugin teardown) have already left every group.
        """
        # Explicit None checks: an empty LayeredDirty is falsy, so `or`
        # would skip a perfectly good (just empty) plugin layer.
        target = getattr(self.view, "plugin_layer", None)
        dedicated = target is not None
        if target is None:
            target = getattr(self.view, "ui_layer", None)
        if target is None:
            return
        if dedicated:
            # The view outlives this state, so sprites from a previous
            # dashboard visit are still in the layer. Adding is idempotent
            # but never *removes*, so a plugin set that changed between
            # visits would leave the old gauges drawn underneath. Only safe
            # on the dedicated layer — ui_layer also holds the chrome.
            target.empty()
        for plugin in self.plugins:
            sprites = getattr(plugin, "sprites", None)
            if sprites is not None:
                target.add(sprites)
        if self.plugin_manager is not None:
            self._linked_generation = self.plugin_manager.generation

    def _relink_if_stale(self) -> None:
        pm = self.plugin_manager
        if pm is not None and pm.generation != self._linked_generation:
            self._link_plugins()
            # A reload may follow a layout sync (new slot arrived) or an
            # feature-grant change — either can change the available pages.
            self._refresh_slot_dots()

    # --- dashboard pages (queried from the exclusive provider) -------------

    def _provider(self):
        """The exclusive dashboard provider instance, if one is loaded.
        The chrome knows nothing about what the pages are — it duck-types
        the provider's paging protocol (pages/active_page/set_active_page)."""
        pm = self.plugin_manager
        return pm.active_provider() if pm is not None else None

    def _pages(self) -> list[str]:
        """Selectable page names from the provider; empty means the single
        built-in view (no provider, or nothing synced yet)."""
        provider = self._provider()
        if provider is None or not hasattr(provider, "pages"):
            return []
        try:
            return list(provider.pages())
        except Exception as e:
            self.logger.warning(f"Provider paging failed: {e}")
            return []

    def _refresh_slot_dots(self) -> None:
        pages = self._pages()
        if not pages:
            self.view.set_slot_pages(1, 0)
            self.view.set_slot_name("")
            return
        # An active page that vanished (unsynced/invalid) renders as the
        # provider's fallback, which reports itself via active_page().
        index = min(self._provider().active_page(), len(pages) - 1)
        self.view.set_slot_pages(len(pages), index)
        # Keep the footer label in step with the dots (covers boot and
        # every reload — a builder rename lands here via the sync reload).
        self.view.set_slot_name(pages[index])

    def _handle_swipe(self, start, end) -> bool:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        skin = active_skin().dashboard
        if abs(dx) < skin.swipe_min_dx or abs(dy) > skin.swipe_max_dy:
            return False

        pages = self._pages()
        if len(pages) < 2:
            return False
        provider = self._provider()
        index = min(provider.active_page(), len(pages) - 1)
        # Swipe left = next page, right = previous; edges don't wrap.
        new_index = min(index + 1, len(pages) - 1) if dx < 0 else max(index - 1, 0)
        if new_index == index:
            return True  # consumed the gesture, nothing to change

        self.logger.info(f"Swipe to dashboard page {new_index}")
        # The provider applies it in-memory and persists off the main
        # thread — a slow SD write must not land exactly at swipe time.
        provider.set_active_page(new_index)
        self.view.set_slot_pages(len(pages), new_index)
        self.view.set_slot_name(pages[new_index])
        if self.plugin_manager is not None:
            # The reload is requested from draw() after the outgoing frame
            # has been snapshotted — two live layouts never coexist, so the
            # slide animates bitmaps: old frame out, freshly painted new
            # layout in.
            self._slide = {"phase": "snapshot", "next": dx < 0}
        return True

    def enter(self, screen):
        rects = super().enter(screen)
        # Linking and the page dots need the borrowed view, so they happen here
        # rather than in __init__ (which runs before the view is acquired).
        self._link_plugins()
        # PluginManager.load_plugins() builds every plugin from
        # LayoutContext.from_config(), so on entry the plugins match config.
        self._plugin_lights = ConfigManager.get_config().status_lights
        self._refresh_slot_dots()
        self.pipeline.start()
        if self.plugin_manager is not None:
            self.plugin_manager.set_dashboard_active(True)

        if self.debug_sender is not None:
            self.debug_sender.start()
            self.logger.info(
                f"Debug sender started: {self.debug_sender.dest_ip}:{self.debug_sender.port}"
            )

        bl = Backlight()
        if bl.available:
            bl.set_percent(ConfigManager.get_config().brightness)
        return rects

    def exit(self):
        if self.debug_sender is not None:
            self.debug_sender.stop()

        if self.plugin_manager is not None:
            self.plugin_manager.set_dashboard_active(False)
        self.pipeline.stop()
        super().exit()

    def on_pause(self):
        # Entering another state mid-slide: drop the transition; the state
        # manager queues a full repaint when we resume.
        self._slide = None
        if self.plugin_manager is not None:
            self.plugin_manager.set_dashboard_active(False)

    def on_resume(self):
        super().on_resume()
        self.pipeline.sync_mode()
        if self.plugin_manager is not None:
            self.plugin_manager.set_dashboard_active(True)

        # The status-lights toggle reshapes the layout: the bezel strips
        # appear/disappear and BOTH widget columns shift inward to clear
        # them. The view reflows its own chrome from config (super() above
        # calls view.reset()), but the gauge plugins are rebuilt only here,
        # so this comparison is what makes the columns move at all.
        #
        # It must be against _plugin_lights, not view.status_lights_enabled:
        # view.reset() has already bound the view's flag to the new value by
        # the time we get here, so comparing against it is always false and
        # the plugins silently keep the old geometry — the Setup button moves
        # aside for the LED strip and the gauges do not.
        status_lights = ConfigManager.get_config().status_lights
        if self.plugin_manager is not None and status_lights != self._plugin_lights:
            self.plugin_manager.relayout(LayoutContext(status_lights=status_lights))
            self._plugin_lights = status_lights
        # No-op when reset() already applied it; kept for the view-less and
        # reset-less paths (extension states subclass this).
        self.view.set_status_lights(status_lights)
        self._relink_if_stale()
        # Slots may have been synced/edited while Setup was open.
        self._refresh_slot_dots()

    def draw(self, surface):
        if self._slide is not None:
            return self._draw_slide(surface)
        return self.view.draw(surface, self.background)

    def _draw_slide(self, surface):
        """Page-slide transition, one phase per call.

        snapshot: copy the outgoing frame (the surface still holds it —
            nothing has drawn this tick), then request the reload; the main
            loop executes it at the top of the next frame.
        wait: hold the old frame until the reload bumped the generation,
            then link the new sprites and paint the incoming layout to an
            offscreen surface.
        anim: slide both bitmaps (ease-out cubic); finish with a normal
            full repaint so the layers' dirty-rect bookkeeping resyncs.
        """
        slide = self._slide
        pm = self.plugin_manager

        if slide["phase"] == "snapshot":
            slide["old"] = surface.copy()
            slide["generation"] = pm.generation
            # A slot switch changes no feature grants — skip the feature
            # provider's (potentially expensive) invalidation.
            pm.request_reload(invalidate_features=False)
            slide["phase"] = "wait"
            return []

        if slide["phase"] == "wait":
            if pm.generation == slide["generation"]:
                return []  # reload not executed yet; keep the old frame
            self._relink_if_stale()
            incoming = pygame.Surface(surface.get_size())
            self.view.full_paint(incoming, self.background)
            slide["new"] = incoming
            slide["start"] = time.monotonic()
            slide["phase"] = "anim"

        if SLIDE_DURATION_S <= 0:
            t = 1.0
        else:
            t = min(1.0, (time.monotonic() - slide["start"]) / SLIDE_DURATION_S)
        eased = 1 - (1 - t) ** 3
        width = surface.get_width()
        offset = round(width * eased)
        direction = 1 if slide["next"] else -1
        surface.blit(slide["old"], (-direction * offset, 0))
        surface.blit(slide["new"], (direction * (width - offset), 0))

        if t >= 1.0:
            self._slide = None
            # Resync the LayeredDirty bookkeeping after frames it never saw.
            self.full_paint(surface)
        return [surface.get_rect()]

    def update(self, dt: float):
        super().update(dt)
        # A plugin reload (e.g. a feature-grant change) may have replaced
        # every plugin instance — link the new sprites into the draw layer.
        self._relink_if_stale()
        self.view.update(self.bus, dt)

    def handle_event(self, event):
        self.view.handle_event(event)

        # Slot swipe: track the pointer from down to up in logical coords.
        # Down/up are never consumed here, so button handling is unaffected
        # (a drag across the Setup button just cancels its press). New
        # gestures are ignored while a slide is in flight.
        if self._slide is not None:
            pass
        elif event.type in (pygame.FINGERDOWN, pygame.MOUSEBUTTONDOWN):
            self._swipe_start = active_profile().to_logical(event)
        elif event.type in (pygame.FINGERUP, pygame.MOUSEBUTTONUP):
            start, self._swipe_start = self._swipe_start, None
            end = active_profile().to_logical(event)
            if start is not None and end is not None:
                if self._handle_swipe(start, end):
                    return True

        if event.type == BUTTON_SETUP_RELEASED:
            self.state_manager.push_state(SetupState(self.state_manager))
            return True
        if event.type == BUTTON_SETUP_LONGPRESSED:
            return True
        return False
