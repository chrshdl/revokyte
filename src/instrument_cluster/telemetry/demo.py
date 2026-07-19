import math
import random
import time

from ..signals.signal_keys import SignalKey
from .models import Bounds, Flags, TelemetryFrame, Wheel, Wheels

SHIFT_INTERVAL = 5.0  # seconds between gear changes
SHIFT_PRE = 0.2  # seconds before change to show in_gear = False


class DemoReader:
    def __init__(self):
        self._t0 = time.perf_counter()

    def start(self) -> None:
        pass

    def latest(self) -> TelemetryFrame:
        t = time.perf_counter() - self._t0
        speed = max(0.0, 36.0 + 36.0 * math.sin(2 * math.pi * (t / 20.0)))  # 38.62
        rpm = int(6500 + 2000 * math.sin(2 * math.pi * (t / 3.0)))

        # cycles every `SHIFT_INTERVAL` seconds: -2, -1, 0, 1, 2, 3, 4, 5, 6
        gear = -2 + int((t // SHIFT_INTERVAL) % 8)

        wheel = Wheel(
            suspension_height=0.0,
            radius=0.0,
            rps=0.0,
            ground_speed=0.0,
            temperature=81.7 + random.Random(int(t // 5)).randint(0, 6),
        )

        wheels = Wheels(
            front_left=wheel,
            front_right=wheel,
            rear_left=wheel,
            rear_right=wheel,
        )

        k = int(t // SHIFT_INTERVAL)
        t_into = t - k * SHIFT_INTERVAL
        t_remaining = SHIFT_INTERVAL - t_into
        in_gear = not (t_remaining <= SHIFT_PRE)

        throttle = max(0.0, math.sin(t) * 0.5 + 0.5)
        brake = max(0.0, math.sin(t + 1.8) * -0.4)

        flags = Flags(
            car_on_track=True,
            in_gear=in_gear,
            # Exercise the bezel status LEDs: TC bites on hard throttle,
            # ASM on braking.
            tcs_active=throttle > 0.85,
            asm_active=brake > 0.25,
        )
        rpm_alert = Bounds(min=6500, max=8000)

        return TelemetryFrame(
            received_time=time.time_ns(),
            car_speed=speed,
            engine_rpm=rpm,
            current_gear=gear,
            throttle=throttle,
            brake=brake,
            steering=math.sin(t / 2.0) * 0.3,
            lap_count=2,
            best_lap_time=97980,  # 0 + int((1000 * t)),
            last_lap_time=0,
            flags=flags,
            rpm_alert=rpm_alert,
            wheels=wheels,
        )

    def stop(self) -> None:
        pass


class DemoDeltaSignal:
    """Produces synthetic delta signals for demo mode.

    Same interface as DeltaSignal.update() so DashboardState
    can use either one without branching.
    """

    def __init__(self):
        self._t0 = time.perf_counter()

    def update(self, frame, signals: dict, dt: float) -> dict:
        t = time.perf_counter() - self._t0
        stable_delta = math.sin(t * 0.125) * 0.6
        return {
            SignalKey.DELTA_DIFF: stable_delta,
            SignalKey.DELTA_DIFF_STABLE: stable_delta,
            # The synthetic delta has no reference lap — clear any mode left
            # in bus.signals by an earlier UDP session so the diff widget
            # falls back to its neutral header.
            SignalKey.DELTA_REFERENCE_MODE: None,
        }


class DemoFuelSignal:
    """Produces synthetic fuel signals for demo mode.

    Same interface as FuelSignal.update() so the pipeline can use either
    one without branching.
    """

    _PER_LAP = 2.6
    _TANK_LAPS = 12.4
    _LAP_SECONDS = 98.0  # matches the demo's ~1:38 best lap

    def __init__(self):
        self._t0 = time.perf_counter()

    _LIVE_REFRESH_S = 3.0  # matches FuelSignal's live readout cadence

    def update(self, frame, signals: dict, dt: float) -> dict:
        t = time.perf_counter() - self._t0
        laps_used = (t / self._LAP_SECONDS) % self._TANK_LAPS
        # Live current-lap burn: restarts at 0.0 each synthetic lap and steps
        # up in the same 5 s cadence as the real signal.
        t_lap = t % self._LAP_SECONDS
        t_held = t_lap - (t_lap % self._LIVE_REFRESH_S)
        return {
            SignalKey.FUEL_PER_LAP: self._PER_LAP,
            SignalKey.FUEL_USED_CURRENT_LAP: t_held / self._LAP_SECONDS * self._PER_LAP,
            SignalKey.FUEL_LAPS_REMAINING: self._TANK_LAPS - laps_used,
        }
