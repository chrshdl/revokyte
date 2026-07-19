from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from ...telemetry.models import TelemetryFrame
    from ..vehicle.vehicle_bus import VehicleBus


class PluginBusView:
    """Read-only facade over VehicleBus exposed to plugins.

    Plugins receive this instead of the full VehicleBus so they cannot
    corrupt shared state via merge_signals(). The signals
    and app_state mappings are wrapped in read-only proxies for the same
    reason (dashboard widgets read them via ``bus.signals.get(...)``).
    """

    def __init__(self, bus: "VehicleBus") -> None:
        self._bus = bus

    @property
    def frame(self) -> "TelemetryFrame | None":
        return self._bus.frame

    @property
    def signals(self) -> Mapping[str, Any]:
        return MappingProxyType(self._bus.signals)

    @property
    def app_state(self) -> Mapping[str, Any]:
        return MappingProxyType(self._bus.app_state)

    def get_signal(self, key: str, default: Any = 0.0) -> Any:
        return self._bus.get_signal(key, default)
