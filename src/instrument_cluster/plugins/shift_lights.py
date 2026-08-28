"""Shift-light LED bar — drives the Blinkt! peripheral.

Free like every standard gauge (a device without the LED bar simply has
nothing to drive). No sprites: this plugin owns hardware.

Deliberately not ``dashboard_only``: like the signal pipeline, a physical
peripheral never pauses for a UI state — freezing the bar mid-pattern in
Setup showed lit LEDs that no longer meant anything. The peripheral's own
guards keep it honest instead (the Setup toggle and stale-link supervision
both blank it, and no frames means nothing to light), and ``teardown()``
blanks the bar so a reload never leaves stale lights on.
"""

from ..core.plugin_system.sdk import GenericPlugin
from ..peripherals.shift_lights import ShiftLights


class ShiftLightsPlugin(GenericPlugin):
    plugin_id = "shift-lights"
    version = "1.3.0"

    def setup(self) -> None:
        self._peripheral = ShiftLights()

    def update(self, dt: float) -> None:
        self._peripheral.update(self.bus, dt)

    def teardown(self) -> None:
        try:
            self._peripheral.exit()
        finally:
            super().teardown()
