"""Post-connectivity entry point.

Every path that hands off to the dashboard (first-boot Wi-Fi connect, Wi-Fi
setup success, the "use demo" skip, and ``main.run``) routes through
:func:`entry_state`. Nothing gates the dashboard: extensions only add
features to an already-running device (see ``extensions.py``).

The ``pipeline`` handed in must be the same ``SignalPipeline`` instance the
main loop updates every frame — the dashboard *starts* it, but the loop is
what pumps it, so a different instance would never receive telemetry.
"""

from __future__ import annotations


def build_dashboard(state_manager, pipeline=None, plugin_manager=None):
    """Construct the dashboard with its UI plugins linked."""
    from .dashboard_state import DashboardState

    return DashboardState(
        state_manager, pipeline=pipeline, plugin_manager=plugin_manager
    )


def entry_state(state_manager, pipeline=None, plugin_manager=None):
    """The dashboard — always. Kept as a seam so every boot path funnels
    through one place (and so future entry conditions have a home)."""
    return build_dashboard(state_manager, pipeline, plugin_manager)
