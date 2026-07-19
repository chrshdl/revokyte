"""Shift-light LED bar — drives the Blinkt! peripheral.

Free like every standard gauge (a device without the LED bar simply has
nothing to drive). No sprites: this plugin owns hardware.
``dashboard_only`` keeps the old cadence (the LEDs only run while the
dashboard is the active state), and ``teardown()`` blanks the bar so a
reload never leaves stale lights on.
"""

from ..core.plugin_system.sdk import GenericPlugin
from ..peripherals.shift_lights import ShiftLights


class ShiftLightsPlugin(GenericPlugin):
    plugin_id = "shift-lights"
    version = "1.1.0"
    dashboard_only = True

    def setup(self) -> None:
        self._peripheral = ShiftLights()

    def update(self, dt: float) -> None:
        self._peripheral.update(self.bus, dt)

    def teardown(self) -> None:
        try:
            self._peripheral.exit()
        finally:
            super().teardown()
