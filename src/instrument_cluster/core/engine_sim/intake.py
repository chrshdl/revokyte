"""Quasi-static intake path: manifold pressure from throttle position.

The runtime consumer is a steady-state table, so manifold *dynamics* are
deliberately absent: per operating point, the throttle-plate orifice flow
is balanced against the engine's pumping demand and solved for MAP by
bisection (vectorized over all grid points at once).
"""

from __future__ import annotations

import numpy as np

from .params import BoostSpec, P_AMBIENT_PA, R_GAS, T_AMBIENT_K
from .valvetrain import orifice_mass_flow

# Effective throttle area vs pedal: area_frac = throttle^_PLATE_EXP,
# plus a small idle bypass so closed throttle still idles.
_PLATE_EXP: float = 1.6
_IDLE_BYPASS_FRAC: float = 0.015
# Reference volumetric efficiency used *only* inside the MAP balance —
# the real VE emerges from the cycle simulation.
_VE_BALANCE: float = 0.90
# WOT target at rated speed used to size the throttle bore.
_WOT_MAP_FRACTION: float = 0.97
_BISECT_ITERS: int = 45


def _smoothstep(x, edge0: float, edge1: float):
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def boost_pa(boost: BoostSpec | None, rpm) -> np.ndarray:
    """Gauge boost vs rpm: spools up between spool_rpm and plateau_rpm,
    then keeps climbing by comp_per_krpm (wastegate compensation)."""
    rpm = np.asarray(rpm, dtype=float)
    if boost is None:
        return np.zeros_like(rpm)
    base = boost.peak_gauge_pa * _smoothstep(
        rpm, 0.6 * boost.spool_rpm, boost.plateau_rpm
    )
    comp_rpm = rpm if boost.comp_cap_rpm is None else np.minimum(rpm, boost.comp_cap_rpm)
    comp = 1.0 + boost.comp_per_krpm * np.maximum(
        comp_rpm - boost.plateau_rpm, 0.0
    ) / 1000.0
    return base * comp


def upstream_pressure(boost: BoostSpec | None, rpm, throttle) -> np.ndarray:
    """Pre-throttle pressure. The wastegate bleeds boost at part throttle."""
    return P_AMBIENT_PA + boost_pa(boost, rpm) * _smoothstep(
        np.asarray(throttle, dtype=float), 0.5, 1.0
    )


def _demand_kg_s(p_man, t_man, vdot_m3_s):
    """Engine pumping demand at manifold density [kg/s]."""
    return _VE_BALANCE * p_man / (R_GAS * t_man) * vdot_m3_s


def size_throttle_area(vdot_redline_m3_s: float, t_man: float) -> float:
    """Throttle bore sized so WOT at rated speed drops ~3% of ambient."""
    p_man = _WOT_MAP_FRACTION * P_AMBIENT_PA
    demand = _demand_kg_s(p_man, t_man, vdot_redline_m3_s)
    unit_flow = orifice_mass_flow(
        np.asarray(P_AMBIENT_PA), np.asarray(t_man), np.asarray(p_man),
        np.asarray(1.0), R_GAS,
    )
    return float(demand / unit_flow)


def solve_map(
    throttle: np.ndarray,
    rpm: np.ndarray,
    a_thr_max: float,
    vdot_per_rpm_m3_s: float,
    t_man: float,
    boost: BoostSpec | None,
) -> np.ndarray:
    """MAP [Pa] per operating point (arrays broadcast together).

    ``vdot_per_rpm_m3_s`` is the swept volume rate per unit rpm
    (Vd_total / (60 * revs_per_cycle)).
    """
    throttle = np.asarray(throttle, dtype=float)
    rpm = np.asarray(rpm, dtype=float)
    p_up = upstream_pressure(boost, rpm, throttle)
    area = a_thr_max * (
        np.clip(throttle, 0.0, 1.0) ** _PLATE_EXP + _IDLE_BYPASS_FRAC
    )
    vdot = vdot_per_rpm_m3_s * np.maximum(rpm, 1.0)

    # f(p) = supply(p) - demand(p) is monotone decreasing -> bisection.
    lo = np.full_like(p_up, 0.03) * p_up
    hi = p_up.copy()
    for _ in range(_BISECT_ITERS):
        mid = 0.5 * (lo + hi)
        supply = orifice_mass_flow(p_up, np.asarray(t_man), mid, area, R_GAS)
        f = supply - _demand_kg_s(mid, t_man, vdot)
        lo = np.where(f > 0.0, mid, lo)
        hi = np.where(f > 0.0, hi, mid)
    return 0.5 * (lo + hi)


def manifold_temperature(boost: BoostSpec | None) -> float:
    from .params import INTERCOOLER_DELTA_K

    return T_AMBIENT_K + (INTERCOOLER_DELTA_K if boost is not None else 0.0)
