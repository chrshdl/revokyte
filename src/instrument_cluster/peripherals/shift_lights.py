from pathlib import Path

from ..core.engine_sim.runtime_model import MappedEngineModel
from ..core.engine_sim.service import get_service
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
        self._map_installed = False

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

    def update(self, bus: VehicleBus, dt: float):
        frame: TelemetryFrame = bus.frame
        if frame is None or frame.flags is None:
            return

        if frame.car_id != self.current_car_id:
            self._init_controller(frame.car_id)

        # The heuristic EngineModel drives the LEDs from the first frame;
        # once the background bake lands, swap in the calibrated map.
        if not self._map_installed:
            baked = get_service().poll(frame.car_id)
            if baked is not None:
                self.controller.install_engine_map(
                    MappedEngineModel(
                        baked,
                        redline=self.controller.engine.redline,
                        on_redline_extend=lambda rpm, car=frame.car_id: (
                            get_service().ensure_rpm(car, rpm)
                        ),
                    )
                )
                self._map_installed = True
                self.logger.info(
                    f"calibrated engine map installed for car {frame.car_id}"
                )

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

    def _init_controller(self, car_id: int):
        """Initializes or updates the controller on car change."""
        car_data = self.car_library.get_specs(car_id)
        self.controller = ShiftLightController(**car_data)
        self.current_car_id = car_id
        self._map_installed = False
        get_service().request(car_id)
        self._force_render_next_frame()

        self.logger.info(
            f"Controller loaded for car {car_id}: {car_data.get('name', 'Unknown')}"
        )

    def _force_render_next_frame(self):
        """Invalidates the cache to ensure the next update pushes to hardware."""
        self._render_cache = []
