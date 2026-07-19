from pathlib import Path
from typing import List, Tuple

from ..core.vehicle.car_profiler import CarLibrary
from ..core.vehicle.ecu import ShiftLightController
from ..core.vehicle.vehicle_bus import VehicleBus
from ..logger import Logger
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

        self.current_car_id = None
        self.controller = None

        self.colors = [
            Color.GREEN.rgb(),
            Color.GREEN.rgb(),
            Color.GREEN.rgb(),
            Color.GREEN.rgb(),
            # Color.ORANGE.rgb(),
            # Color.RED.rgb(),
        ]

        # cache to track the current color of every pixel
        # prevents sending data to hardware when nothing has changed
        self._render_cache: List[Tuple[int, int, int]] = [
            Color.BLACK.rgb()
        ] * self.ledbar.NUM_PIXELS

    def exit(self) -> None:
        self.ledbar.reset()

    def update(self, bus: VehicleBus, dt: float):
        frame: TelemetryFrame = bus.frame
        if frame is None or frame.flags is None:
            return

        if frame.car_id != self.current_car_id:
            self._init_controller(frame.car_id)

        lights, is_alert, is_tcs, is_asm = self.controller.calculate_lights(frame, dt)

        target_state = [Color.BLACK.rgb()] * self.ledbar.NUM_PIXELS

        if is_alert:
            if any(lights):
                blue = Color.BLUE.rgb()
                target_state = [blue] * self.ledbar.NUM_PIXELS
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

    def _init_controller(self, car_id: int):
        """Initializes or updates the controller on car change."""
        car_data = self.car_library.get_specs(car_id)
        self.controller = ShiftLightController(**car_data)
        self.current_car_id = car_id
        self._force_render_next_frame()

        self.logger.info(
            f"Controller loaded for car {car_id}: {car_data.get('name', 'Unknown')}"
        )

    def _force_render_next_frame(self):
        """Invalidates the cache to ensure the next update pushes to hardware."""
        self._render_cache = []
