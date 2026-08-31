from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..config import ConfigManager
from ..core.vehicle.car_profiler import CarClassLibrary, CarLibrary
from ..core.vehicle.ecu import ShiftLightController, power_droop_for
from ..core.vehicle.vehicle_bus import VehicleBus
from ..logger import Logger

if TYPE_CHECKING:
    from ..telemetry.models import TelemetryFrame
from ..ui.colors import Color
from .ledbar import LEDBar, create_ledbar


class ShiftLights:
    def __init__(self) -> None:
        self.logger = Logger(__class__.__name__).get()
        self.ledbar: LEDBar = create_ledbar()

        UPPER_DIR = Path(__file__).resolve().parent.parent
        DATA_DIR = UPPER_DIR / "db"
        cars_path = DATA_DIR / "cars.json"

        self.car_library = CarLibrary(filepath=cars_path)
        # Engine class is looked up for *every* car, including the ones whose
        # peaks arrive on the wire: the sender supplies the curve's peaks, this
        # supplies its shape.
        self.car_class_library = CarClassLibrary(
            filepath=DATA_DIR / "car_classes.json"
        )

        # Identity of the specs the current controller was built from:
        # (car_id, engine-curve tuple or None, rev limiter). Wire-supplied
        # engine data participates so a sender updating its curve rebuilds the
        # controller just like a car change does, and the limiter does too —
        # it anchors the shift target, so a retuned car is a different car as
        # far as the shift point is concerned.
        self._profile_key: tuple | None = None
        self.controller = None

        self.colors = [
            Color.GREEN.rgb(),
            Color.GREEN.rgb(),
            Color.ORANGE.rgb(),
            Color.RED.rgb(),
        ]

        # cache to track the current color of every pixel
        # prevents sending data to hardware when nothing has changed
        self._render_cache: list[tuple[int, int, int]] = [
            Color.BLACK.rgb()
        ] * self.ledbar.NUM_PIXELS

    def exit(self) -> None:
        self.ledbar.reset()

    def _blank_once(self) -> None:
        """Blank the bar if anything is lit (the render cache tells us),
        then stay silent — no SPI traffic while there is nothing to show."""
        if any(c != Color.BLACK.rgb() for c in self._render_cache):
            self.ledbar.reset()
            self._render_cache = [Color.BLACK.rgb()] * self.ledbar.NUM_PIXELS

    def update(self, bus: VehicleBus, dt: float):
        if not ConfigManager.get_config().shift_lights:
            # Blank exactly once on the off-edge, never leave the bar
            # frozen mid-pattern.
            self._blank_once()
            return

        if bus.signals.get("telemetry_stale"):
            # Dead link (mode switch away from a running feed, crashed
            # feed, sleeping console, dropped Wi-Fi): readers hold their
            # last frame forever, so without this the controller keeps
            # rendering stale RPM. The screen deliberately keeps its
            # gauges under the NO SIGNAL banner, but lit LEDs on dead
            # telemetry read as live state — blank them.
            self._blank_once()
            return

        frame: TelemetryFrame = bus.frame
        if frame is None or frame.flags is None:
            return

        engine = frame.engine
        profile_key = (
            frame.car_id,
            (
                engine.max_power_kw,
                engine.max_power_rpm,
                engine.max_torque_nm,
                engine.max_torque_rpm,
                engine.power_to_limiter,
            )
            if engine is not None
            else None,
            frame.rpm_alert.max if frame.rpm_alert is not None else None,
        )
        if profile_key != self._profile_key:
            self._init_controller(frame, profile_key)

        lights, is_alert, is_tcs, is_asm = self.controller.calculate_lights(frame, dt)

        target_state = [Color.BLACK.rgb()] * self.ledbar.NUM_PIXELS

        if is_alert:
            if any(lights):
                red = Color.RED.rgb()
                target_state = [red] * self.ledbar.NUM_PIXELS
        else:
            on_count = sum(lights) // 2

            for p in range(self.ledbar.NUM_PIXELS // 2):
                if p < on_count:
                    color = self.colors[p]

                    left = p
                    right = self.ledbar.NUM_PIXELS - 1 - p

                    target_state[left] = color
                    target_state[right] = color

            if is_tcs:
                orange = Color.ORANGE.rgb()
                target_state[0] = orange
                target_state[self.ledbar.NUM_PIXELS - 1] = orange
            if is_asm:
                blue = Color.BLUE.rgb()
                mid_left = (self.ledbar.NUM_PIXELS // 2) - 1
                mid_right = self.ledbar.NUM_PIXELS // 2
                target_state[mid_left] = blue
                target_state[mid_right] = blue

        if target_state != self._render_cache:
            for i, color in enumerate(target_state):
                self.ledbar.set_pixel(i, *color)
            self.ledbar.show()
            self._render_cache = target_state

    def _init_controller(self, frame: TelemetryFrame, profile_key: tuple):
        """(Re)builds the controller when the car or its wire specs change.

        Spec precedence (PROTOCOL.md §3.5.5): an engine curve supplied on
        the wire wins — the sender knows its game's cars, and its data
        updates with feed releases instead of image releases. The local
        cars.json is the fallback for senders that cannot supply one (GT7's
        feed keyed by its car_id space), degrading further to a generic
        profile for unknown ids.
        """
        engine = frame.engine
        if engine is not None:
            # Redline arrives separately as rpm_alert.max (and is refreshed
            # from it every frame); the +1000 mirrors the cars.json pattern
            # for the frames before the first rpm_alert lands.
            redline = (
                frame.rpm_alert.max
                if frame.rpm_alert is not None and frame.rpm_alert.max > 0
                else engine.max_power_rpm + 1000.0
            )
            car_data = {
                "name": f"wire profile (car {frame.car_id})",
                "max_power_kw": engine.max_power_kw,
                "max_power_rpm": engine.max_power_rpm,
                "max_torque_nm": engine.max_torque_nm,
                "max_torque_rpm": engine.max_torque_rpm,
                "redline_rpm": redline,
                "power_to_limiter": engine.power_to_limiter,
            }
        else:
            car_data = self.car_library.get_specs(frame.car_id)

        # The falloff past the power peak comes from the car's class, on both
        # paths: the wire's four peaks cannot express it, and a sender that
        # does know says so with power_to_limiter, which still wins.
        car_class = self.car_class_library.get_class(frame.car_id) or {}
        car_data["power_droop"] = power_droop_for(
            car_class.get("aspiration"), car_class.get("car_type")
        )

        self.controller = ShiftLightController(**car_data)
        self._profile_key = profile_key
        self._force_render_next_frame()

        self.logger.info(
            f"Controller loaded for car {frame.car_id}: "
            f"{car_data.get('name', 'Unknown')} "
            f"[{car_class.get('aspiration') or '??'}/"
            f"{car_class.get('car_type') or '??'}, "
            f"droop {self.controller.engine.power_droop:.2f}]"
        )
        self.logger.info(f"Redline RPM: {car_data.get('redline_rpm', 'Unknown')}")

    def _force_render_next_frame(self):
        """Invalidates the cache to ensure the next update pushes to hardware."""
        self._render_cache = []
