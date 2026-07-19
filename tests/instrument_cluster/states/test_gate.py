"""The entry gate: every device reaches the dashboard — nothing gates
the boot."""

from dataclasses import dataclass, field
from unittest.mock import MagicMock

from instrument_cluster.states.dashboard_state import DashboardState
from instrument_cluster.states.gate import entry_state


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


def test_entry_is_always_the_dashboard():
    state = entry_state(MockStateManager())
    assert isinstance(state, DashboardState)


def test_plugins_are_linked_into_the_dashboard():
    plugin = MagicMock()
    plugin_manager = MagicMock(plugins=[plugin])
    state = entry_state(MockStateManager(), plugin_manager=plugin_manager)
    assert isinstance(state, DashboardState)
    assert plugin in state.plugins
