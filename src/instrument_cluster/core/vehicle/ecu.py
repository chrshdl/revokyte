from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import numpy as np

from ...logger import Logger
from ...telemetry.units import ThrottleNormalizer

if TYPE_CHECKING:
    from ...telemetry.models import TelemetryFrame

# EngineModel torque curve shape
_TORQUE_LOW_BLEND_BASE: float = 0.4  # fraction of max torque at rpm=0
_TORQUE_LOW_BLEND_SLOPE: float = (
    0.6  # additional fraction gained linearly to peak-torque rpm
)
# How fast power falls away past the peak, the one thing the four peak numbers
# on the wire cannot say. Stated as *power retained at a reference over-rev*
# because that is what a dyno measures and what the class priors below were
# calibrated as; the droop the curve uses is derived from it.
#
# The reference is a fixed constant, never the car's own limiter: the shape
# must stay anchored on max_power_rpm, since cars.json's redline_rpm column is
# fabricated (539 of 540 rows are exactly max_power_rpm + 1000) and a
# redline-anchored falloff lets invented data reshape a real car's curve.
_REFERENCE_OVER_REV: float = 0.20

# Values by engine class (see db/car_classes.json). A turbocharged road engine
# holds power almost to the limiter, a BOP'd race engine holds it flat, and a
# naturally aspirated one droops — which is the reverse of the intuition the
# first priors here encoded. Each value below was measured off a real car —
# full-throttle pulls in two gears, fitted with aerodynamic drag in the model
# — and the comment on each says which car and how strong the evidence is.
#
# MEASURED. Car 3588 (Ferrari 296 GT3 '23), 10 full-throttle pulls across 2nd
# and 3rd, 2535 samples, 3000-7870 rpm: best fit droop 0.03, and 0.10 fitting
# from 4900 rpm up. The fit error climbs 6.9% by droop 2.5, so this is a real
# minimum and not a flat likelihood. The measurement tracks the flat curve
# within ±0.03 the whole way and sits *above* it at the limiter, so if
# anything a race engine holds power slightly better than constant power.
# Aerodynamic drag is fitted alongside it (1.5 m/s² at 200 km/h) — without
# that the same data reads as droop 1.48.
_RETENTION_RACE: float = 1.00  # flat — the shift-cost margin holds it in gear
# MEASURED. Car 3487 (Mustang Boss 429 '69), 13 pulls across 2nd, 3rd and 4th,
# 5188 samples, power peaking at 5000 and pulling to 6155 — 23% of over-rev,
# which is what gives this one real leverage on an NA engine. Best fit droop
# 0.80, and it is the only car measured whose data rules *out* flat: the fit
# error rises on both sides of the minimum, by 1.8% at droop 0. So the V8
# genuinely droops where both turbos do not, and the aspiration split is real
# — it is the direction the original priors got wrong, not the existence of a
# difference. (The first reading of this car said 0.62, from 5 runs before a
# pull held at terminal velocity was excluded from the fit.)
#
# It covers every naturally aspirated road car, high-revving ones included.
# There used to be a separate, gentler value for engines peaking above 7000
# rpm, on the reasoning that a short-stroke screamer holds power better. It
# was never measured and cannot be: such an engine peaks a few percent under
# its limiter by design, so there is almost no over-rev region for a falloff
# to act in. Car 204 (Civic Type R (EK) '98) was driven to settle it — 16
# pulls, 7853 samples — and its fit error varies by 0.1% across the entire
# droop range, which is what "no information" looks like in a tool that
# prints two decimals regardless. Extrapolating one V8 to a VTEC is a guess
# too, but a traceable one, and on these engines it moves the shift point by
# a few rpm.
_RETENTION_NA: float = 0.84

# No supercharged car was available to drive, so this inherits the measured
# forced-induction value rather than a number of its own. A blower makes
# boost in proportion to rpm, which is why a supercharged engine belongs with
# the turbos here and not with the naturally aspirated ones. 15 cars.
_RETENTION_TURBO: float = 0.98
_RETENTION_SUPERCHARGED: float = _RETENTION_TURBO
# Unknown car, unknown class (non-GT7 feeds, a car missing from the table):
# the assumption this model made for every car before the classes existed.
_RETENTION_DEFAULT: float = 0.90



def _droop(retention: float) -> float:
    """Power lost per unit of over-rev, from power retained at the reference."""
    return max(0.0, (1.0 - retention) / _REFERENCE_OVER_REV)


_DEFAULT_POWER_DROOP: float = _droop(_RETENTION_DEFAULT)


def power_droop_for(aspiration: str | None, car_type: str | None) -> float:
    """Falloff for one car's engine class (db/car_classes.json fields).

    Either field may be None or empty — an unknown car, or a feed for a game
    with no class table — in which case the historical default applies.
    """
    aspiration = (aspiration or "").upper()
    car_type = (car_type or "").lower()

    if aspiration == "EV":
        # No over-rev region worth modelling, and single-speed anyway: there
        # is no upshift to compute, so the curve never decides anything.
        return 0.0
    if car_type == "race":
        return _droop(_RETENTION_RACE)
    if aspiration in ("TC", "TC+SC"):
        return _droop(_RETENTION_TURBO)
    if aspiration == "SC":
        return _droop(_RETENTION_SUPERCHARGED)
    if aspiration == "NA":
        return _droop(_RETENTION_NA)
    return _DEFAULT_POWER_DROOP

# An upshift costs ~0.15 s of zero thrust, so the true break-even genuinely
# favours staying in gear — and under flat power the bare crossover is
# degenerate (torque proportional to 1/rpm makes wheel torque identical in both
# gears, leaving the comparison to floating-point noise). Race engines live in
# exactly that region, so the next gear must beat the current one by this
# margin, not merely tie it.
_SHIFT_COST_MARGIN: float = 0.08

# Reaction time, expressed in rpm below the limiter. Real shift bars go red at
# ~97-98% of the limiter; car-relative so a 15000 rpm kart and a 5700 rpm hatch
# both get a usable amount of warning.
_TARGET_LEAD_FRAC: float = 0.02
_TARGET_LEAD_RPM_MIN: float = 60.0
_TARGET_LEAD_RPM_MAX: float = 250.0

# Bounds on the blink lead, so an odd ratio pair cannot put the cue absurdly
# early or leave it too late to react to.
_CUE_LEAD_RPM_MIN: float = 80.0
_CUE_LEAD_RPM_MAX: float = 400.0

# Ladder width, as a fraction of the RPM the engine actually drops on the
# upshift out of this gear. That drop is the natural car-and-gear-relative
# scale — it narrows with every gear exactly as the old hand-fitted per-gear
# multipliers tried to, but derived per car instead of guessed once for all of
# them, so a 5700 rpm hatch and a 15000 rpm kart no longer share a corridor.
# How far below the shift point the ladder starts, as a fraction of the rev
# limiter. Deliberately **not** derived from the gear ratio: the driver reads
# this bar against a tach that does not change with gear, and when a sender
# sets power_to_limiter the shift point is the same rpm in every gear. Sizing
# the ladder per gear made 7000 rpm show two pairs in 1st, one in 3rd and
# nothing in 5th on the same car — the bar meant something different in every
# gear. The gear-dependence that *is* real lives in the blink lead below.
_CORRIDOR_FRAC_OF_LIMITER: float = 0.20

# How far the blink leads the shift point, as a fraction of the RPM the engine
# drops on the upshift. This is the part that must scale with gear: it is
# reaction time expressed in rpm, and rpm climbs ~4x faster in 1st than in 4th
# (measured on car 3588: 1497 vs 387 rpm/s). The upshift drop is the proxy —
# it is derived from the same gear ratio that sets the climb rate.
_CUE_LEAD_FRAC_OF_DROP: float = 0.1125

# Blink lead when the ratios are unknown (demo mode, the ACC broadcast feed) —
# a flat fraction of the limiter, since there is nothing to scale by.
_NO_RATIO_CUE_LEAD_FRAC: float = 0.02

# How far below the shift point the bar starts blinking, as a fraction of the
# corridor. The blink is a cue to *act*, so it has to fire early enough that a
# human reacting to it lands on the shift point — a driver needs ~185 ms, and
# in that time rpm climbs by rate x 0.185, which is four times further in 1st
# than in 4th. Measured on a 296 GT3 (car 3588): 1497/939/556/387 rpm/s in
# gears 1-4, so reacting to a blink at the shift point itself overshot into
# the limiter in 1st and 2nd. Scaling the lead by the corridor gets the
# gear-dependence for free: the corridor is derived from the upshift rpm drop,
# which scales with the same gear ratio the climb rate does. At 0.15 the blink
# lands within ~70 rpm of the ideal cue in every gear.
_CUE_LEAD_FRAC: float = 0.15

# Where each LED pair lights, as a fraction of the window below the shift
# point. The gaps between them — and between the last pair and the blink —
# must shrink monotonically, so the ramp reads as accelerating all the way
# into the shift. These give 0.38 / 0.28 / 0.21 / 0.13 of the window.
#
# The previous [0.00, 0.35, 0.60, 0.75] spaced them 0.35 / 0.25 / 0.15 / 0.25:
# the ramp tightened, then the final step *widened* again, so the bar snapped
# to fully-lit and then held there longer than the step before it. That reads
# as a stall at the one moment that matters, and makes the full pattern
# ambiguous — go now, or is there more? The blink is the cue; a full bar means
# the next thing to happen is the blink.
_DEFAULT_SHIFT_FRACTIONS: list[float] = [0.00, 0.38, 0.66, 0.87]

# Learning the real rev limiter.
#
# `rpm_alert.max` is what the game *declares*, and on GT7 it is a tachometer
# value, not the fuel cut: car 1461 declares 8000 and cuts at 7215, measured
# across three full-throttle pulls that all stopped within 3 rpm of each
# other. A target anchored on the declared value then sits 625 rpm above
# anything the engine can reach, so the ladder never completes and the blink
# never fires — the bar reads two greens while the game is already flashing.
#
# The cut has a signature nothing else has: rpm falling while the pedal is on
# the floor and the gear has not changed. Learn from that, and only ever
# downward — a declared limiter is an upper bound worth trusting until the
# engine itself contradicts it.
_LIMITER_CUT_DROP_RPM: float = 150.0
# Ignore a "cut" far below the declared limit; that is wheelspin, a missed
# gear or a bad frame, not a rev limiter.
_LIMITER_MIN_FRAC: float = 0.75
# Pedal position that counts as full throttle for the purpose above.
_LIMITER_WOT_THROTTLE: float = 0.9

# Schmitt-trigger hysteresis to prevent RPM flicker around thresholds
_HYSTERESIS_RPM: float = 60.0
_ALERT_EXIT_HYSTERESIS_RPM: float = 200.0

# Shift-alert blink period in seconds
_BLINK_PERIOD_S: float = 0.10

# RPM window size limits
# Absolute bounds on the ladder width. These are a backstop against absurd
# limiters, not a tuning knob: the corridor is already a fraction of the
# limiter, so it scales on its own. They were much tighter when the corridor
# came from the gear ratios, and that 1800 ceiling silently capped 115 of the
# 540 cars in the table — every engine revving past ~9000 got the same ladder
# as a 9000 rpm one, which is exactly the scaling this is supposed to provide.
_WINDOW_RPM_MIN: float = 600.0
_WINDOW_RPM_MAX: float = 3500.0

# Gear-ratio change tolerance — avoids recreating ShiftPointCalculator on floating-point noise
_RATIO_CHANGE_TOLERANCE: float = 1e-3

# Redline change tolerance — same purpose, for a jittery wire rpm_alert.max
_REDLINE_CHANGE_TOLERANCE: float = 10.0

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
        power_to_limiter: bool = False,
        power_droop: float | None = None,
    ):
        self.redline = redline_rpm
        # A sender that knows the engine holds power to the limiter turns the
        # droop off entirely; the shift-cost margin then keeps every gear at
        # the limiter, which is where race cars are actually shifted. It wins
        # over the class prior: the sender knows this car, the table only
        # knows its class.
        if power_to_limiter:
            self.power_droop = 0.0
        elif power_droop is not None:
            self.power_droop = float(power_droop)
        else:
            self.power_droop = _DEFAULT_POWER_DROOP
        self.max_power_rpm = max_power_rpm
        self.max_torque_rpm = max_torque_rpm
        self.max_torque_nm = max_torque_nm

        self.torque_at_power_peak = (max_power_kw * 9549) / max_power_rpm

    def get_torque(self, rpm: float) -> float:
        """Returns estimated torque in Nm."""
        # Hold the redline value rather than falling off a cliff to zero: a
        # step discontinuity inside the scanned range invents crossovers.
        rpm = min(rpm, self.redline)

        # if below peak torque do linear ramp up
        if rpm < self.max_torque_rpm:
            blend = _TORQUE_LOW_BLEND_BASE + _TORQUE_LOW_BLEND_SLOPE * (
                rpm / self.max_torque_rpm
            )
            return self.max_torque_nm * blend

        # ensure we are moving from max_torque down to torque_at_power_peak
        drop_range = self.max_power_rpm - self.max_torque_rpm
        if drop_range <= 0:
            drop_range = 1.0

        # Clamped at 1.0: this interpolates *between* the torque and power
        # peaks and has no meaning past the latter. Left unclamped it kept
        # squaring — at 8200 rpm on a 6800 rpm power peak it reached 4.31 and
        # cut a Ferrari 296 GT3 from 628 Nm to 345 Nm, which is what made the
        # shift lights blink over 1000 rpm early.
        dist = min(1.0, (rpm - self.max_torque_rpm) / drop_range)
        drop_amount = max(0, self.max_torque_nm - self.torque_at_power_peak)

        torque = self.max_torque_nm - (drop_amount * (dist**2))

        if rpm > self.max_power_rpm:
            # Past the power peak, model *power* and let torque follow: a real
            # engine holds power far better than the old curve assumed, and
            # constant power alone is torque proportional to 1/rpm.
            over_rev = (rpm / self.max_power_rpm) - 1.0
            power_frac = max(0.0, 1.0 - self.power_droop * over_rev)
            torque = self.torque_at_power_peak * (self.max_power_rpm / rpm) * power_frac

        return max(0.0, float(torque))


class ShiftPointCalculator:
    def __init__(self, engine: EngineModel, gear_ratios: list[float]):
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

            status = "SHIFT!" if t_next > t_curr * (1.0 + _SHIFT_COST_MARGIN) else "STAY"

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

                # Shift only once the next gear beats the current one by the
                # cost of the upshift itself (see _SHIFT_COST_MARGIN).
                if torque_next > torque_now * (1.0 + _SHIFT_COST_MARGIN):
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
        power_to_limiter: bool = False,
        power_droop: float | None = None,
        shiftlight_fractions: list[float] | None = None,
        filter_window: int = 3,
    ):
        self.engine = EngineModel(
            max_power_kw,
            max_power_rpm,
            max_torque_nm,
            max_torque_rpm,
            redline_rpm,
            power_to_limiter,
            power_droop,
        )
        self.calculator: ShiftPointCalculator | None = None
        self.last_gear_ratios = None
        # Redline the current calculator was scanned against.
        self._built_redline: float | None = None

        self._rpm_buffer = deque([0.0] * filter_window, maxlen=filter_window)

        # Dynamic Window Config
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

        # Rev-limiter learning (see _LIMITER_CUT_DROP_RPM).
        self._throttle = ThrottleNormalizer()
        self._wot_max_rpm = 0.0
        self._observed_limiter: float | None = None
        self._limiter = float(redline_rpm)

        # state
        self._pair_count = 0
        self._in_alert = False
        self._target_rpm = 0.0
        self._last_gear = 0

        self._logger = Logger(type(self).__name__).get()

        # cache
        self._thresholds_by_gear: dict[int, list[float]] = {}
        self._shift_rpm_by_gear: dict[int, float] = {}
        self._alert_rpm_by_gear: dict[int, float] = {}

    def _clamp(self, x: float, lo: float, hi: float) -> float:
        return lo if x < lo else min(x, hi)

    def _upshift_drop_rpm(self, gear: int, target: float) -> float | None:
        """RPM the engine drops on the upshift out of ``gear``, or None when
        the ratios cannot say.

        GT7 reads eight ratio slots and stops at the first zero, but some
        seven-speed layouts hold an unrelated float in the eighth — so a pair
        that does not actually shorten the drivetrain is not a gear pair, and
        trusting it would yield a zero or negative corridor.
        """
        ratios = self.last_gear_ratios
        if not ratios or gear < 1 or gear >= len(ratios):
            return None
        current, following = ratios[gear - 1], ratios[gear]
        if not 0.0 < following < current:
            return None
        return target * (1.0 - following / current)

    def _compute_window_rpm(self, gear: int, shift_rpm: float) -> float:
        """How much RPM the ladder spans below the shift point."""
        base = _CORRIDOR_FRAC_OF_LIMITER * float(self._limiter)
        return self._clamp(base, self.window_rpm_min, self.window_rpm_max)

    def _compute_alert_rpm(self, gear: int, shift_rpm: float) -> float:
        """RPM the bar starts blinking — the shift point, led by reaction time."""
        drop = self._upshift_drop_rpm(gear, shift_rpm)
        if drop is None:
            lead = _NO_RATIO_CUE_LEAD_FRAC * float(self._limiter)
        else:
            lead = _CUE_LEAD_FRAC_OF_DROP * drop
        return shift_rpm - self._clamp(lead, _CUE_LEAD_RPM_MIN, _CUE_LEAD_RPM_MAX)

    def _compute_thresholds(self, gear: int, shift_rpm: float) -> list[float]:
        start_rpm = shift_rpm - self._compute_window_rpm(gear, shift_rpm)
        # The pairs run from that fixed low end up to the blink — so the bottom
        # of the ladder is the same rpm in every gear, while the top follows
        # the gear-dependent cue lead and the last pair always lands just under
        # the blink instead of leaving a gap.
        span = max(200.0, self._compute_alert_rpm(gear, shift_rpm) - start_rpm)
        return [start_rpm + f * span for f in self.fractions]

    def _learn_limiter(self, frame: TelemetryFrame, rpm: float, gear: int) -> None:
        """Watch for the engine refusing to rev any further.

        A fuel cut is rpm falling while the pedal is down in an unchanged
        gear. A lift is not (the pedal comes up), an upshift is not (the gear
        changes, and the caller has already reset this), and wheelspin
        recovering is not — that happens far below the declared limit, which
        is what _LIMITER_MIN_FRAC excludes.
        """
        throttle = self._throttle(frame.throttle)
        if throttle < _LIMITER_WOT_THROTTLE or gear < 1:
            self._wot_max_rpm = 0.0
            return

        if rpm > self._wot_max_rpm:
            self._wot_max_rpm = rpm
            return

        if rpm > self._wot_max_rpm - _LIMITER_CUT_DROP_RPM:
            return  # noise, not a cut

        declared = float(self.engine.redline)
        cut = self._wot_max_rpm
        self._wot_max_rpm = 0.0
        if cut < _LIMITER_MIN_FRAC * declared:
            return
        if self._observed_limiter is not None and cut <= self._observed_limiter:
            return

        self._observed_limiter = cut
        self._shift_rpm_by_gear.clear()
        self._thresholds_by_gear.clear()
        self._alert_rpm_by_gear.clear()
        self._logger.info(
            "rev limiter learned: %.0f rpm (the game declares %.0f)", cut, declared
        )

    def _reset_states_on_gear_change(self, gear: int):
        self._wot_max_rpm = 0.0
        self._pair_count = 0
        self._in_alert = False
        self._blink_t = 0.0
        self._blink_on = True
        self._last_gear = gear

    def _update_blink(self, dt: float) -> bool:
        # toggles every blink_period; starts as "ON" on entry
        self._blink_t += dt
        while self._blink_t >= self.blink_period:
            self._blink_t -= self.blink_period
            self._blink_on = not self._blink_on
        return self._blink_on

    def _update_pair_count(self, rpm: float, thresholds: list[float]) -> int:
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
    ) -> tuple[list[bool], bool, bool, bool]:
        dt = (
            _DEFAULT_DT_S if (dt is None or dt <= 0.0) else self._clamp(dt, 0.001, 0.05)
        )

        gear = frame.current_gear

        # filter RPM to stop red bleeding (median by sort — np.median's
        # dispatch overhead costs ~0.15 ms per 60 Hz frame on the Pi)
        self._rpm_buffer.append(float(frame.engine_rpm))
        buf = sorted(self._rpm_buffer)
        mid = len(buf) // 2
        rpm = buf[mid] if len(buf) % 2 else 0.5 * (buf[mid - 1] + buf[mid])

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

        self._learn_limiter(frame, rpm, gear)

        # update redline from telemetry; keep the DB redline if the frame
        # carries no rev-limit (rpm_alert absent — a legal omission the ACC
        # broadcast feed always makes — or max == 0)
        if frame.rpm_alert is not None and frame.rpm_alert.max > 0:
            self.engine.redline = frame.rpm_alert.max

        # Rebuild the calculator when the ratios change — with a tolerance, so
        # floating-point noise on the wire does not recreate it every frame —
        # or when the redline moves. The redline trigger matters because the
        # curve is scanned relative to it: without it, a limiter arriving after
        # the ratios (or a retuned car) left a stale curve in place forever.
        if frame.gear_ratios:
            ratios_changed = False
            if self.last_gear_ratios is None or len(frame.gear_ratios) != len(
                self.last_gear_ratios
            ):
                ratios_changed = True
            else:
                # only update if a ratio differs by more than 0.001
                for r1, r2 in zip(frame.gear_ratios, self.last_gear_ratios):
                    if abs(r1 - r2) > _RATIO_CHANGE_TOLERANCE:
                        ratios_changed = True
                        break

            redline_changed = (
                self._built_redline is None
                or abs(self.engine.redline - self._built_redline)
                > _REDLINE_CHANGE_TOLERANCE
            )

            if ratios_changed or redline_changed:
                self.last_gear_ratios = frame.gear_ratios
                self._built_redline = self.engine.redline
                self.calculator = ShiftPointCalculator(self.engine, frame.gear_ratios)
                self._thresholds_by_gear.clear()
                self._shift_rpm_by_gear.clear()
                self._alert_rpm_by_gear.clear()

        # Shift RPM target for this gear, anchored on the rev limiter — the
        # one per-car number the game itself tells us, and the only thing we
        # have at all without gear ratios on the wire (demo mode and the ACC
        # broadcast feed never send them). The power curve may only move the
        # target *down* from there.
        # The declared limiter is an upper bound; the engine's own cut wins
        # over it once observed.
        limiter = float(self.engine.redline)
        if self._observed_limiter is not None:
            limiter = min(limiter, self._observed_limiter)
        self._limiter = limiter
        lead = self._clamp(
            _TARGET_LEAD_FRAC * limiter, _TARGET_LEAD_RPM_MIN, _TARGET_LEAD_RPM_MAX
        )
        shift_rpm = limiter - lead
        if self.calculator:
            shift_rpm = min(float(self.calculator.get_optimal_rpm(gear)), shift_rpm)

        # Deliberately *not* clamped to rpm_alert.min. That clamp existed so
        # the 4th LED pair could not be skipped when the game's own
        # rev_limiter_alert_active preempted the ladder — a real bug, but it
        # was fixed by dragging the target down to the game's warning rpm,
        # ~500 below the limiter, on every car. The interloper is gone
        # instead: the alert keys on our own target alone (see enter_alert),
        # so the ladder always runs to completion and the target can sit
        # where the engine actually wants it.

        self._target_rpm = shift_rpm

        if (
            gear not in self._thresholds_by_gear
            or abs(self._shift_rpm_by_gear.get(gear, 0) - shift_rpm) > 5.0
        ):
            self._shift_rpm_by_gear[gear] = shift_rpm
            self._thresholds_by_gear[gear] = self._compute_thresholds(gear, shift_rpm)
            self._alert_rpm_by_gear[gear] = self._compute_alert_rpm(gear, shift_rpm)
            # Once per gear per car, so free at 60 Hz — and the only way to
            # audit shift points against *real* limiters and *real* ratios.
            # An offline sweep can only use the fabricated redline column.
            self._logger.info(
                "shift point: gear %d  limiter %.0f%s  target %.0f (%.0f%%)  "
                "blink %.0f  pairs %s  game warns at %s",
                gear,
                limiter,
                ""
                if self._observed_limiter is None
                else f" (declared {self.engine.redline:.0f})",
                shift_rpm,
                100.0 * shift_rpm / limiter if limiter else 0.0,
                self._alert_rpm_by_gear[gear],
                [round(t) for t in self._thresholds_by_gear[gear]],
                round(frame.rpm_alert.min) if frame.rpm_alert else "n/a",
            )

        thresholds = self._thresholds_by_gear[gear]
        alert_rpm = self._alert_rpm_by_gear[gear]

        # The alert is ours alone. The game's rev_limiter_alert_active turns
        # on at rpm_alert.min — that is a warning band, and our own ladder
        # already draws one, per gear and better timed. Two red states on the
        # same eight LEDs would be two clocks telling different times.
        enter_alert = rpm >= alert_rpm
        exit_alert = rpm <= (alert_rpm - self.alert_exit_hys_rpm)

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
