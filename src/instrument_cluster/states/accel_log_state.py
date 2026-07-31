"""Accel-run logger state: capture full-throttle pulls for the current car.

Pushed from the dashboard's Dyno button. The SignalPipeline keeps running
in the main loop while this state is active (data acquisition is never
paused by UI state), so the recorder simply reads the live frame off the
bus every tick. Leaving the state loses nothing — accepted runs are on
disk the moment they end.
"""

from __future__ import annotations

from pathlib import Path

from ..core.engine_sim.accel_recorder import (
    AccelRunRecorder,
    AccelRunStore,
    RecorderState,
    default_runs_dir,
)
from ..core.vehicle.car_profiler import CarLibrary
from ..logger import Logger
from ..ui.colors import Color
from ..ui.events import BUTTON_BACK_RELEASED
from ..ui.views.accel_log_view import AccelLogView
from .state import State

_AMBER = (255, 180, 40)


class AccelLogState(State):
    def __init__(self, state_manager=None):
        super().__init__(state_manager)
        self.logger = Logger(__class__.__name__).get()
        self.bus = state_manager.vehicle_bus

        store = AccelRunStore(default_runs_dir())
        self.recorder = AccelRunRecorder(store)

        cars_path = Path(__file__).resolve().parent.parent / "db" / "cars.json"
        self._car_library = CarLibrary(filepath=cars_path)

        self.view = AccelLogView(save_dir=str(store.base_dir))
        self._shown_car: int | None = -2  # force the first refresh
        self._shown_result = None

    def background_color(self):
        return self.view.background_color

    def draw_static_background(self, bg):
        self.view.draw_static_elements(bg)

    def create_group(self):
        return None

    def full_paint(self, surface):
        self.view.full_paint(surface, self.background)

    def draw(self, surface):
        return self.view.draw(surface, self.background)

    def update(self, dt):
        super().update(dt)

        frame = self.bus.frame
        self.recorder.feed(frame)
        self._refresh_view(frame)
        self.view.update(dt)

    def _refresh_view(self, frame) -> None:
        recorder = self.recorder

        if recorder.car_id != self._shown_car:
            self._shown_car = recorder.car_id
            if recorder.car_id is None:
                self.view.set_car("no live car (demo / no telemetry)", live=False)
            else:
                specs = self._car_library.get_specs(recorder.car_id)
                self.view.set_car(
                    f"{specs.get('name') or 'unknown car'}  (id {recorder.car_id})",
                    live=True,
                )
            self.view.set_runs(recorder.runs_on_disk())

        if recorder.state == RecorderState.RECORDING:
            self.view.set_capture_state("RECORDING", Color.RED.rgb())
        elif recorder.state == RecorderState.ARMED:
            self.view.set_capture_state("ARMED - FLOOR IT", _AMBER)
        else:
            self.view.set_capture_state("WAITING FOR TELEMETRY", _AMBER)

        if frame is not None and frame.car_id >= 0:
            self.view.set_live(
                frame.current_gear, frame.engine_rpm, min(1.0, frame.throttle)
            )

        result = recorder.last_result
        if result is not None and result is not self._shown_result:
            self._shown_result = result
            if result.accepted:
                self.view.set_result(
                    f"saved: gear {result.gear}, "
                    f"{int(result.rpm_lo)}-{int(result.rpm_hi)} rpm "
                    f"({result.reason})",
                    good=True,
                )
                self.logger.info(f"accel run saved: {result.path}")
            else:
                self.view.set_result(f"discarded: {result.reason}", good=False)
            self.view.set_runs(recorder.runs_on_disk())

    def handle_event(self, event):
        if self.view.handle_event(event):
            return True
        if event.type == BUTTON_BACK_RELEASED:
            self.state_manager.pop_state()
            return True
        return False
