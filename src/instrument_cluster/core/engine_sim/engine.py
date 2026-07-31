"""EngineSimulator: one calibrated engine, ready to integrate grids."""

from __future__ import annotations

import numpy as np

from .combustion import afr_at_load, burn_duration_deg, start_of_combustion_deg
from .cycle import OperatingPoints, build_tables, run_cycles
from .friction import fmep_pa
from .geometry import CylinderGeometry
from .intake import (
    boost_pa,
    manifold_temperature,
    size_throttle_area,
    solve_map,
)
from .params import EngineParams, P_AMBIENT_PA, R_GAS

# Resolution profiles: the fitter iterates dozens of curves and can live
# with 2 deg / 2 cycles; baked maps and validation use full resolution.
FIT_STEP_DEG: float = 2.0
FIT_MAX_CYCLES: int = 2
FULL_STEP_DEG: float = 1.0
FULL_MAX_CYCLES: int = 3


def _smoothstep(x, edge0, edge1):
    t = np.clip((x - edge0) / np.maximum(edge1 - edge0, 1.0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def correction_blend(correction: dict | None, rpm) -> np.ndarray:
    """The calibrated multiplicative torque correction: a smooth,
    bounded, monotone blend from k_torque to k_power."""
    c = correction or {}
    k_t = c.get("k_torque", 1.0)
    k_p = c.get("k_power", 1.0)
    return k_t + (k_p - k_t) * _smoothstep(
        np.asarray(rpm, dtype=float),
        c.get("rpm_torque", 3000.0),
        c.get("rpm_power", 6000.0),
    )


class EngineSimulator:
    def __init__(self, params: EngineParams):
        self.params = params
        self.cyl = CylinderGeometry(params.geometry)
        self.t_man = manifold_temperature(params.boost)
        geo = params.geometry
        self._vdot_per_rpm = (geo.displacement_l * 1e-3) / (60.0 * geo.revs_per_cycle)
        self._a_thr = size_throttle_area(
            self._vdot_per_rpm * params.rated_rpm, self.t_man
        )
        self._tables_cache: dict[float, object] = {}

    def _tables(self, step_deg: float):
        if step_deg not in self._tables_cache:
            self._tables_cache[step_deg] = build_tables(
                self.cyl, self.params.cam, step_deg
            )
        return self._tables_cache[step_deg]

    # Combined charge multipliers are capped: intake tricks hold VE up,
    # they don't manufacture boost.
    _CHARGE_FACTOR_MAX = 1.45

    def _ram_factor(self, rpm) -> np.ndarray:
        """Charge-pressure multiplier at the valve: the runner-resonance
        bump/deficit around the tuned speed, plus the fitted charge
        sustain (VVT equivalent) rising between its anchor rpms."""
        p = self.params
        rpm = np.asarray(rpm, dtype=float)
        rel = rpm / max(p.ram_tune_rpm, 1.0)
        bump = p.ram_gain * np.exp(-(((rel - 1.0) / 0.35) ** 2))
        low = p.ram_low_penalty * np.clip(1.0 - rel, 0.0, 1.0) ** 2
        factor = 1.0 + bump - low
        if p.charge_comp_per_krpm > 0.0:
            comp_rpm = rpm if p.charge_comp_cap_rpm is None else np.minimum(
                rpm, p.charge_comp_cap_rpm
            )
            factor = factor * (
                1.0
                + p.charge_comp_per_krpm
                * np.maximum(comp_rpm - p.charge_comp_from_rpm, 0.0)
                / 1000.0
            )
        return np.minimum(factor, self._CHARGE_FACTOR_MAX)

    def _correction(self, rpm) -> np.ndarray:
        return correction_blend(self.params.correction, rpm)

    def simulate_grid(
        self,
        rpm_axis: np.ndarray,
        throttle_axis: np.ndarray,
        step_deg: float = FULL_STEP_DEG,
        max_cycles: int = FULL_MAX_CYCLES,
        apply_correction: bool = True,
        pace_hook=None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Brake torque [Nm] and fuel flow [g/s], shape (n_rpm, n_throttle).

        The whole grid is one flattened batch through the integrator —
        wall-clock scales with crank-angle steps, not grid size.
        """
        p = self.params
        rpm_axis = np.asarray(rpm_axis, dtype=float)
        throttle_axis = np.asarray(throttle_axis, dtype=float)
        rpm_g, thr_g = np.meshgrid(rpm_axis, throttle_axis, indexing="ij")
        rpm = rpm_g.ravel()
        thr = thr_g.ravel()

        is_ci = p.combustion.kind == "ci"
        if is_ci:
            # No throttle plate: full manifold pressure, load via fueling.
            p_man = np.full_like(rpm, P_AMBIENT_PA) + boost_pa(p.boost, rpm)
            ci_frac = np.clip(thr, 0.0, 1.0)
        else:
            p_man = solve_map(
                thr, rpm, self._a_thr, self._vdot_per_rpm, self.t_man, p.boost
            )
            ci_frac = None
        p_man = p_man * self._ram_factor(rpm)
        if p.geometry.kind == "two_stroke":
            # Crankcase scavenging delivers the charge above ambient —
            # without this the ports (both open around BDC) sit below
            # exhaust backpressure and the cylinder never fills fresh.
            p_man = p_man * 1.35

        soc_signed = start_of_combustion_deg(p.combustion, rpm)
        cycle_deg = p.geometry.cycle_deg
        soc_rel = ((soc_signed % cycle_deg) - p.cam.ivc_deg) % cycle_deg

        ops = OperatingPoints(
            rpm=rpm,
            p_man=p_man,
            t_man=np.full_like(rpm, self.t_man),
            soc_rel_deg=soc_rel,
            burn_deg=burn_duration_deg(p.combustion, rpm),
            afr=afr_at_load(p.combustion, thr),
            ci_fuel_frac=ci_frac,
            two_stroke_trap_eff=(
                0.75 if p.geometry.kind == "two_stroke" else None
            ),
            comb_efficiency=p.combustion.comb_efficiency,
            lhv_j_kg=p.combustion.lhv_j_kg,
            smoke_limit_afr=p.combustion.smoke_limit_afr,
        )
        res = run_cycles(
            self._tables(step_deg), ops, p.combustion.wiebe_a, p.combustion.wiebe_m,
            max_cycles=max_cycles, pace_hook=pace_hook,
        )

        bmep = res.imep_pa - fmep_pa(
            p.fmep, res.p_max_pa, self.cyl.mean_piston_speed(rpm)
        )
        vd_total = p.geometry.displacement_l * 1e-3
        torque = bmep * vd_total / (2.0 * np.pi * p.geometry.revs_per_cycle)
        if apply_correction:
            torque = torque * self._correction(rpm)
            cap_nm = (p.correction or {}).get("cap_nm")
            if cap_nm is not None:
                # Torque-limited boost control (Veyron class): the ECU
                # clips the mid-range flat at rated torque.
                torque = np.minimum(torque, cap_nm)

        cycles_per_s = rpm / (60.0 * p.geometry.revs_per_cycle)
        fuel_g_s = res.fuel_kg_per_cycle * p.geometry.n_cyl * cycles_per_s * 1e3

        shape = (len(rpm_axis), len(throttle_axis))
        return torque.reshape(shape), fuel_g_s.reshape(shape)

    def simulate_wot(
        self,
        rpm_axis: np.ndarray,
        step_deg: float = FIT_STEP_DEG,
        max_cycles: int = FIT_MAX_CYCLES,
        apply_correction: bool = True,
    ) -> np.ndarray:
        """WOT brake torque curve [Nm] — the fitter's workhorse."""
        torque, _ = self.simulate_grid(
            rpm_axis,
            np.asarray([1.0]),
            step_deg=step_deg,
            max_cycles=max_cycles,
            apply_correction=apply_correction,
        )
        return torque[:, 0]
