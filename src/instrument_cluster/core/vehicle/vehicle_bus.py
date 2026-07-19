import threading
from dataclasses import dataclass, field
from typing import Any

from ..system.system_health_monitor import SystemHealthMonitor
from ...telemetry.models import TelemetryFrame


@dataclass
class VehicleBus:
    # raw frame from GT7
    frame: TelemetryFrame | None = None

    # enriched data calculated by plugins (for example 'tire_slip', 'fuel_req')
    signals: dict[str, Any] = field(default_factory=dict)

    # internal app state (for example 'is_shifting', 'delta_color')
    app_state: dict[str, Any] = field(default_factory=dict)

    health: SystemHealthMonitor = field(default_factory=SystemHealthMonitor)

    # protects concurrent writes to signals from background threads
    _signals_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    # protects frame writes; update_frame() is main-thread-only in practice but
    # this lock makes the contract explicit and safe under free-threaded Python.
    _frame_lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def update_frame(self, new_frame: TelemetryFrame) -> None:
        with self._frame_lock:
            self.frame = new_frame

    def merge_signals(self, updates: dict) -> None:
        with self._signals_lock:
            self.signals.update(updates)

    def get_signal(self, key: str, default: Any = 0.0) -> Any:
        """Unified signal lookup: frame attrs → signals dict → app_state."""
        frame = self.frame
        if frame is not None and hasattr(frame, key):
            return getattr(frame, key)
        with self._signals_lock:
            if key in self.signals:
                return self.signals[key]
        return self.app_state.get(key, default)

    def tick(self, dt: float):
        self.health.update(dt)
