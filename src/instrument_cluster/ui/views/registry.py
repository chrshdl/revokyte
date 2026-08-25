"""Process-lifetime ownership of every view.

Views used to be constructed by their ``State`` in ``__init__`` and dropped when
the state was popped. Nothing leaked — but a view is mostly SDL surfaces
allocated in C, while CPython's collector is driven by *object counts*, so the
runtime could not see the cost of what it was holding. Navigating the menus
accumulated tens of megabytes invisibly until one gen-2 collection freed them
all at once, dropping the cluster to 3 fps for about a second at an arbitrary
moment.

The fix is the rule production automotive HMI stacks share: allocate at startup,
never during runtime. The screen set is bounded and known at design time, so
every view is built once and lives for the whole process; a transition rebinds
data through :meth:`View.reset` instead of constructing.

``acquire()`` builds lazily on first use and ``preload()`` builds a known set
eagerly — the same code path either way. That keeps "eager or lazy?" a one-line
policy choice at the call site rather than two designs: drop the ``preload()``
in ``main.py`` and boot goes back to paying per screen on first visit.
"""

from __future__ import annotations

import weakref

from ...core.system import unhealthy
from ...logger import Logger


def core_views() -> tuple[type, ...]:
    """The views the community build ships. Imported lazily so importing the
    registry does not drag every view module (and its skin lookups) in."""
    from .agent_setup_view import AgentSetupView
    from .dashboard_view import DashboardView
    from .enter_ip_view import EnterIPView
    from .install_view import InstallView
    from .listener_setup_view import ListenerSetupView
    from .setup_view import SetupView
    from .software_view import SoftwareView
    from .wifi_setup_view import WifiSetupView

    return (
        DashboardView,
        SetupView,
        SoftwareView,
        EnterIPView,
        WifiSetupView,
        InstallView,
        AgentSetupView,
        ListenerSetupView,
    )


class ViewRegistry:
    """Owns every view for the life of the process.

    Construction is legal only once a display exists — views resolve
    ``active_skin()`` in ``__init__`` — so the eager ``preload()`` runs after
    ``Display()``, and after extensions have wired, but before the first frame.
    """

    def __init__(self):
        self.logger = Logger(__class__.__name__).get()
        self._views: dict[type, object] = {}
        # Classes whose build() raised. Kept so a broken view is reported once
        # at build time, not on every visit to the screen that wants it.
        self._failed: set[type] = set()
        # cls -> weakref to the State currently holding it. Weak so a registry
        # that outlives every state does not keep those states alive.
        self._borrowed: dict[type, weakref.ref] = {}

    # ------------------------------------------------------------------
    def preload(self, classes) -> None:
        """Build a known set up front. Failures are logged and skipped."""
        for cls in classes:
            self._build(cls)

    def _build(self, cls):
        if cls in self._views:
            return self._views[cls]
        if cls in self._failed:
            return None
        try:
            view = cls()
            view.build()
        except Exception:
            # Fail open: one unbuildable view must not blank the dashboard.
            # The owning state degrades to a view-less screen and everything
            # else comes up. But a view is baked into the image, so rolling
            # back is exactly the cure — publish it where the OTA health check
            # can withhold mark-good, or a bad update would be marked good and
            # never roll back.
            self.logger.exception("View %s failed to build", cls.__name__)
            self._failed.add(cls)
            unhealthy.report(f"view {cls.__name__} failed to build")
            return None
        self._views[cls] = view
        return view

    def acquire(self, cls, borrower=None):
        """The single instance of ``cls``, built on first use.

        ``None`` when the class could not be built, or when ``cls`` is ``None``
        (a state that declares no view). Callers must cope with ``None``.
        """
        if cls is None:
            return None
        view = self._build(cls)
        if view is None:
            return None

        previous = self._borrowed.get(cls)
        holder = previous() if previous is not None else None
        if holder is not None and holder is not borrower:
            # Two live states sharing one view instance would have them
            # corrupting each other's screen. Logged rather than raised:
            # StateManager wraps every state callback in try/except, so an
            # exception here would be swallowed and leave a blank screen
            # instead of a diagnosable one.
            self.logger.error(
                "View %s acquired by %s while still borrowed by %s — "
                "the two states will corrupt each other's screen",
                cls.__name__,
                type(borrower).__name__,
                type(holder).__name__,
            )
        self._borrowed[cls] = self._track(borrower)
        return view

    @staticmethod
    def _track(borrower):
        """Weak handle on the borrower, or None when it cannot be weakly
        referenced. Borrow tracking is a development aid — it must never be
        the thing that raises inside State.enter()."""
        if borrower is None:
            return None
        try:
            return weakref.ref(borrower)
        except TypeError:
            return None

    def release(self, cls, borrower=None) -> None:
        """Give the view back. A stale release (the class has since been
        acquired by someone else) is ignored."""
        previous = self._borrowed.get(cls)
        if previous is None:
            self._borrowed.pop(cls, None)
            return
        holder = previous()
        if holder is None or holder is borrower:
            del self._borrowed[cls]

    def clear(self) -> None:
        """Drop every built view. Tests only — views bake in the active skin at
        construction, so a cached view would leak the wrong profile across
        tests that use the ``force_profile`` fixture."""
        self._views.clear()
        self._failed.clear()
        self._borrowed.clear()

    # -- introspection, for tests and the budget assertion --------------
    @property
    def built(self) -> tuple[type, ...]:
        return tuple(self._views)

    @property
    def failed(self) -> tuple[type, ...]:
        return tuple(self._failed)


# Module-level singleton, mirroring extensions.runtime: the registry is process
# state, and states reach it without threading it through 19 constructors.
views = ViewRegistry()
