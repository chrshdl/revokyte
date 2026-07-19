from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np

from ...telemetry.models import TelemetryFrame

# EngineModel torque curve shape
_TORQUE_LOW_BLEND_BASE: float = 0.8    # fraction of max torque at rpm=0
_TORQUE_LOW_BLEND_SLOPE: float = 0.2   # additional fraction gained linearly to peak-torque rpm
_OVER_REV_TORQUE_DROP: float = 0.25   # fraction of peak-power torque lost by redline

# ShiftLightController gear-scale factors (window width multipliers per gear)
_GEAR_SCALE_1: float = 1.15   # gear 1 gets more lead time
_GEAR_SCALE_2: float = 1.05   # gear 2 gets slightly more lead time
_GEAR_SCALE_HIGH: float = 0.90  # gears >= 5 get a tighter window

# Default progressive shift-light activation fractions (fraction of RPM window)
_DEFAULT_SHIFT_FRACTIONS: List[float] = [0.00, 0.35, 0.60, 0.75]

# Schmitt-trigger hysteresis to prevent RPM flicker around thresholds
_HYSTERESIS_RPM: float = 60.0
_ALERT_EXIT_HYSTERESIS_RPM: float = 120.0

# Shift-alert blink period in seconds
_BLINK_PERIOD_S: float = 0.10

# RPM window size limits
_WINDOW_RPM_MIN: float = 800.0
_WINDOW_RPM_MAX: float = 2000.0

# Gear-ratio change tolerance — avoids recreating ShiftPointCalculator on floating-point noise
_RATIO_CHANGE_TOLERANCE: float = 1e-3

# Default dt when none is provided or value is non-positive
_DEFAULT_DT_S: float = 0.016


class EngineModel:
    def __init__(
        self,
        max_power_kw,
        max_power_rpm,
        max_torque_nm,
        max_torque_rpm,
        redline_rpm,
    ):
        self.redline = redline_rpm
        self.max_power_rpm = max_power_rpm
        self.max_torque_rpm = max_torque_rpm
        self.max_torque_nm = max_torque_nm

        self.torque_at_power_peak = (max_power_kw * 9549) / max_power_rpm

    def get_torque(self, rpm: float) -> float:
        """Returns estimated torque in Nm."""
        if rpm > self.redline:
            return 0.0

        # if below peak torque do linear ramp up
        if rpm < self.max_torque_rpm:
            blend = _TORQUE_LOW_BLEND_BASE + _TORQUE_LOW_BLEND_SLOPE * (rpm / self.max_torque_rpm)
            return self.max_torque_nm * blend

        # ensure we are moving from max_torque down to torque_at_power_peak
        drop_range = self.max_power_rpm - self.max_torque_rpm
        if drop_range <= 0:
            drop_range = 1.0

        dist = (rpm - self.max_torque_rpm) / drop_range
        drop_amount = max(0, self.max_torque_nm - self.torque_at_power_peak)

        torque = self.max_torque_nm - (drop_amount * (dist**2))

        if rpm > self.max_power_rpm:
            # force a drop of _OVER_REV_TORQUE_DROP from peak power torque
            # by the time we hit redline
            over_rev_range = self.redline - self.max_power_rpm
            if over_rev_range > 0:
                pct_past = (rpm - self.max_power_rpm) / over_rev_range
                torque *= 1.0 - _OVER_REV_TORQUE_DROP * (pct_past**2)

        return max(0.0, float(torque))


class ShiftPointCalculator:
    def __init__(self, engine: EngineModel, gear_ratios: List[float]):
        self.engine = engine
        self.ratios = gear_ratios
        self.optimal_shift_rpms = {}
        self._calculate()

    def debug_plot_shift(self, gear_idx: int):
        """Prints a text-based graph of Wheel Torque for Current vs Next Gear."""
        current_ratio = self.ratios[gear_idx]
        next_ratio = self.ratios[gear_idx + 1]

        print(f"\n--- Analysis: Gear {gear_idx + 1} vs {gear_idx + 2} ---")
        print("RPM  | Cur Wheel Torque | Next Wheel Torque | Status")
        print("-" * 60)

        for rpm in np.linspace(self.engine.redline * 0.7, self.engine.redline, 24):
            # RPM we land at if we shift NOW
            rpm_next = rpm * (next_ratio / current_ratio)

            # wheel torque = engine Torque * ratio
            t_curr = self.engine.get_torque(rpm) * current_ratio
            t_next = self.engine.get_torque(rpm_next) * next_ratio

            status = "SHIFT!" if t_next > t_curr else "STAY"

            print(f"{int(rpm):4d} | {int(t_curr):16d} | {int(t_next):17d} | {status}")

    def _calculate(self):
        # we scan the RPM range to find where wheel torque crosses over
        scan_rpms = np.linspace(self.engine.redline * 0.6, self.engine.redline, 250)

        for gear_idx in range(len(self.ratios) - 1):
            current_ratio = self.ratios[gear_idx]
            next_ratio = self.ratios[gear_idx + 1]

            best_rpm = self.engine.redline

            for rpm in scan_rpms:
                # Calculate what RPM we would land at in the next gear
                # Ratio of RPMs is inverse to Ratio of Gears
                next_rpm = rpm * (next_ratio / current_ratio)

                # Torque at Wheels = Engine Torque * Gear Ratio
                # (We ignore final drive as it cancels out on both sides of equation)
                torque_now = self.engine.get_torque(rpm) * current_ratio
                torque_next = self.engine.get_torque(next_rpm) * next_ratio

                # The moment Next Gear gives more torque than Current Gear -> SHIFT!
                if torque_next > torque_now:
                    best_rpm = rpm
                    break

            # Map gear number (1-based) to the rpm
            self.optimal_shift_rpms[gear_idx + 1] = best_rpm

    def get_optimal_rpm(self, gear: int) -> float:
        return self.optimal_shift_rpms.get(gear, self.engine.redline)


class ShiftLightController:
    def __init__(
        self,
        name="Car Name",
        max_power_kw=400,
        max_power_rpm=8500,
        max_torque_nm=600,
        max_torque_rpm=6500,
        redline_rpm=9000,
        shiftlight_fractions: Optional[List[float]] = None,
        filter_window: int = 3,
        target_corridor: float = 1600.0,
    ):
        self.engine = EngineModel(
            max_power_kw, max_power_rpm, max_torque_nm, max_torque_rpm, redline_rpm
        )
        self.calculator: ShiftPointCalculator | None = None
        self.last_gear_ratios = None

        self._rpm_buffer = deque([0.0] * filter_window, maxlen=filter_window)

        # Dynamic Window Config
        self.target_corridor = target_corridor
        self.window_rpm_min = _WINDOW_RPM_MIN
        self.window_rpm_max = _WINDOW_RPM_MAX

        # Progressive fractions: each LED pair lights when RPM crosses
        # that fraction of the window below the shift point.
        self.fractions = shiftlight_fractions or list(_DEFAULT_SHIFT_FRACTIONS)

        # hysteresis: prevents flicker around thresholds
        self.hys_rpm = _HYSTERESIS_RPM
        # alert hysteresis: prevents 1-frame overshoot
        self.alert_exit_hys_rpm = _ALERT_EXIT_HYSTERESIS_RPM

        # blink timing in seconds
        self.blink_period = _BLINK_PERIOD_S
        self._blink_t = 0.0
        self._blink_on = True

        # state
        self._pair_count = 0
        self._in_alert = False
        self._target_rpm = 0.0
        self._last_gear = 0

        # cache
        self._thresholds_by_gear: Dict[int, List[float]] = {}
        self._shift_rpm_by_gear: Dict[int, float] = {}

    def _clamp(self, x: float, lo: float, hi: float) -> float:
        return lo if x < lo else hi if x > hi else x

    def _gear_scale(self, gear: int) -> float:
        if gear == 1:
            return _GEAR_SCALE_1
        if gear == 2:
            return _GEAR_SCALE_2
        if gear >= 5:
            return _GEAR_SCALE_HIGH
        return 1.00

    def _compute_window_rpm(self, gear: int) -> float:
        """
        Window is 'target_corridor' wide, widened for low gears
        (more lead time) and tightened for high gears.
        """
        base = self.target_corridor * self._gear_scale(gear)
        return self._clamp(base, self.window_rpm_min, self.window_rpm_max)

    def _compute_thresholds(self, gear: int, shift_rpm: float) -> List[float]:
        window = self._compute_window_rpm(gear)
        start_rpm = shift_rpm - window
        # thresholds are increasing RPM points
        # where each additional pair turns on
        return [start_rpm + f * window for f in self.fractions]

    def _reset_states_on_gear_change(self, gear: int):
        self._pair_count = 0
        self._in_alert = False
        self._blink_t = 0.0
        self._blink_on = True
        self._last_gear = gear

    def _update_blink(self, dt: float) -> bool:
        # toggles every blink_period; starts as "ON" on entry
        self._blink_t += dt
        while self._blink_t >= self.blink_period:
            self._blink_t = 0.0
            self._blink_on = not self._blink_on
        return self._blink_on

    def _update_pair_count(self, rpm: float, thresholds: List[float]) -> int:
        """
        Schmitt-trigger state machine that maps
        RPM to pair_count with hysteresis.
        """

        # this is the state (memory)
        pc = self._pair_count

        # step up as RPM crosses the upper threshold
        while pc < len(thresholds) and rpm >= thresholds[pc]:
            pc += 1

        # step down only after dropping below lower threshold (threshold - hysteresis)
        while pc > 0 and rpm < (thresholds[pc - 1] - self.hys_rpm):
            pc -= 1

        self._pair_count = pc
        return pc

    def calculate_lights(
        self, frame: TelemetryFrame, dt: float | None = None
    ) -> Tuple[List[bool], bool, bool, bool]:
        dt = _DEFAULT_DT_S if (dt is None or dt <= 0.0) else self._clamp(dt, 0.001, 0.05)

        gear = frame.current_gear

        # filter RPM to stop red bleeding
        self._rpm_buffer.append(float(frame.engine_rpm))
        rpm = np.median(self._rpm_buffer)

        rev_alert = frame.flags.rev_limiter_alert_active
        tcs_active = frame.flags.tcs_active
        asm_active = frame.flags.asm_active

        if gear <= 0:
            # neutral / reverse -> no shift lights
            self._pair_count = 0
            self._in_alert = False
            return [False] * 8, False, False, False

        # reset on gear change
        if gear != self._last_gear:
            self._reset_states_on_gear_change(gear)

        # update redline from telemetry; keep the DB redline if the
        # frame carries no rev-limit (rpm_alert.max == 0)
        if frame.rpm_alert.max > 0:
            self.engine.redline = frame.rpm_alert.max

        # build calculator if ratios changed
        # and add a tolerance check for gear ratios
        # floating-point "noise" to prevent recreating
        # ShiftPointCalculator every single frame.
        if frame.gear_ratios:
            ratios_changed = False
            if self.last_gear_ratios is None:
                ratios_changed = True
            elif len(frame.gear_ratios) != len(self.last_gear_ratios):
                ratios_changed = True
            else:
                # only update if a ratio differs by more than 0.001
                for r1, r2 in zip(frame.gear_ratios, self.last_gear_ratios):
                    if abs(r1 - r2) > _RATIO_CHANGE_TOLERANCE:
                        ratios_changed = True
                        break

            if ratios_changed:
                self.last_gear_ratios = frame.gear_ratios
                self.calculator = ShiftPointCalculator(self.engine, frame.gear_ratios)
                self._thresholds_by_gear.clear()
                self._shift_rpm_by_gear.clear()

        if not self.calculator:
            return [False] * 8, False, False, False

        # shift RPM target for this gear
        optimal = float(self.calculator.get_optimal_rpm(gear))
        shift_rpm = min(optimal, float(self.engine.redline) - 40.0)
        self._target_rpm = shift_rpm

        if (
            gear not in self._thresholds_by_gear
            or abs(self._shift_rpm_by_gear.get(gear, 0) - shift_rpm) > 5.0
        ):
            self._shift_rpm_by_gear[gear] = shift_rpm
            self._thresholds_by_gear[gear] = self._compute_thresholds(gear, shift_rpm)

        thresholds = self._thresholds_by_gear[gear]

        # enter alert if either rev limiter alert is active
        # or we exceeded shift_rpm
        enter_alert = rev_alert or (rpm >= shift_rpm)

        # exit alert only if the flag is off
        # and RPM has fallen below the exit threshold
        exit_alert = (not rev_alert) and (rpm <= (shift_rpm - self.alert_exit_hys_rpm))

        if not self._in_alert:
            if enter_alert:
                self._in_alert = True
                self._blink_t = 0.0
                self._blink_on = True
        else:
            if exit_alert:
                self._in_alert = False
                self._blink_t = 0.0
                self._blink_on = True

        if self._in_alert:
            on = self._update_blink(dt)
            return ([True] * 8 if on else [False] * 8), True, False, False

        pairs = self._update_pair_count(rpm, thresholds)

        leds = [False] * 8
        for i in range(pairs):
            leds[i] = leds[7 - i] = True

        # return leds, False, tcs_active, asm_active
        return leds, False, False, False

    @property
    def target_rpm(self) -> float:
        return self._target_rpm
