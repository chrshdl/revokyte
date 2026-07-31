"""Single-zone, crank-angle-resolved cycle integrator.

One sweep runs a full cycle from IVC (the natural anchor: trapped mass is
known there, so the fuel charge is too) through compression, burn,
expansion, blowdown, exhaust, overlap and induction back to IVC. The
first law is marched in crank angle with a fixed-step Heun scheme,
**vectorized across operating points**: state and accumulators are
shape-(N,) arrays, the theta-dependent tables are shared, so a whole
RPM x throttle grid integrates in one pass. Cycles repeat with
residual-gas carry-over until IMEP settles.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .combustion import wiebe_fraction
from .geometry import CylinderGeometry
from .params import (
    CamSpec,
    EXHAUST_BACKPRESSURE_PA,
    R_GAS,
    WALL_TEMPERATURE_K,
)
from .thermo import cp as _cp, cv as _cv, woschni_h
from .valvetrain import area_profile, orifice_mass_flow

# Temperature of burned gas re-ingested from the exhaust port during
# overlap backflow.
_EXHAUST_PORT_T_K: float = 900.0
_T_MIN_K: float = 150.0
_T_MAX_K: float = 4000.0
_M_MIN_KG: float = 1e-9
_IMEP_CONVERGENCE: float = 0.005


@dataclass
class CycleTables:
    """theta-dependent quantities shared by every operating point."""

    theta_rel: np.ndarray  # sweep-relative degrees, 0 at IVC, (n+1,)
    volume: np.ndarray  # m^3
    dv_dtheta: np.ndarray  # m^3/rad
    a_intake: np.ndarray  # effective flow area m^2
    a_exhaust: np.ndarray
    a_wall: np.ndarray  # heat-transfer area m^2
    step_deg: float
    cycle_deg: float
    ivc_deg: float
    # Sweep index where the intake opens: the mass present then is what
    # remains of the previous cycle — the residual-gas sample point.
    residual_index: int
    bore: float
    v_displaced: float


def build_tables(cyl: CylinderGeometry, cam: CamSpec, step_deg: float) -> CycleTables:
    cycle = cyl.geo.cycle_deg
    n_steps = int(round(cycle / step_deg))
    theta_rel = np.arange(n_steps + 1) * step_deg
    theta_abs = (cam.ivc_deg + theta_rel) % cycle

    a_int = area_profile(
        theta_abs, cam.ivo_deg, cam.ivc_deg,
        cam.intake_area_frac * cyl.piston_area, cycle, cam.shape_p,
    )
    a_exh = area_profile(
        theta_abs, cam.evo_deg, cam.evc_deg,
        cam.exhaust_area_frac * cyl.piston_area, cycle, cam.shape_p,
    )
    ivo_rel = (cam.ivo_deg - cam.ivc_deg) % cycle
    return CycleTables(
        theta_rel=theta_rel,
        volume=cyl.volume(theta_abs),
        dv_dtheta=cyl.dvolume_dtheta(theta_abs),
        a_intake=a_int,
        a_exhaust=a_exh,
        a_wall=cyl.wall_area(theta_abs),
        step_deg=step_deg,
        cycle_deg=cycle,
        ivc_deg=cam.ivc_deg,
        residual_index=int(round(ivo_rel / step_deg)) % n_steps,
        bore=cyl.bore,
        v_displaced=cyl.v_displaced,
    )


@dataclass
class OperatingPoints:
    """Per-point inputs, all shape (N,)."""

    rpm: np.ndarray
    p_man: np.ndarray  # Pa
    t_man: np.ndarray  # K
    soc_rel_deg: np.ndarray  # start of combustion, sweep-relative
    burn_deg: np.ndarray
    afr: np.ndarray  # SI mixture strength
    ci_fuel_frac: np.ndarray | None = None  # CI: fueling fraction 0..1
    # Two-strokes scavenge instead of exhaling: fresh charge is a fixed
    # fraction of the trapped mass, not (trapped - residual).
    two_stroke_trap_eff: float | None = None
    mean_piston_speed: np.ndarray | None = None  # filled in by run_cycles
    comb_efficiency: float = 0.96
    lhv_j_kg: float = 44.0e6
    smoke_limit_afr: float = 18.0
    wall_t_k: float = WALL_TEMPERATURE_K
    heat_transfer: bool = True
    combustion: bool = True


@dataclass
class CycleResult:
    imep_pa: np.ndarray  # net indicated (incl. pumping), per cylinder
    p_max_pa: np.ndarray
    air_kg_per_cycle: np.ndarray
    fuel_kg_per_cycle: np.ndarray
    cycles_run: int
    # First-law bookkeeping over the last cycle (for closure tests).
    work_j: np.ndarray
    q_comb_j: np.ndarray
    q_ht_j: np.ndarray
    h_in_j: np.ndarray
    h_out_j: np.ndarray
    du_j: np.ndarray


def _rhs(tables: CycleTables, k: int, m, t, ops: OperatingPoints, omega, m_fuel, spec):
    """theta-domain derivatives at table index k. Returns
    (dm_dtheta, dT_dtheta, p, dW_dtheta, dQc_dtheta, dQh_dtheta,
    dHin_dtheta, dHout_dtheta)."""
    v = tables.volume[k]
    dv = tables.dv_dtheta[k]
    a_in = tables.a_intake[k]
    a_ex = tables.a_exhaust[k]
    a_w = tables.a_wall[k]
    theta_rel = tables.theta_rel[k]

    p = m * R_GAS * t / v

    # Valve flows, signed into the cylinder.
    mdot_in = np.zeros_like(m)
    mdot_out = np.zeros_like(m)
    h_in_rate = np.zeros_like(m)

    if a_in > 0.0:
        fwd = orifice_mass_flow(ops.p_man, ops.t_man, p, a_in, R_GAS)
        rev = orifice_mass_flow(p, t, ops.p_man, a_in, R_GAS)
        intake_fwd = ops.p_man >= p
        flow_in = np.where(intake_fwd, fwd, 0.0)
        flow_bf = np.where(intake_fwd, 0.0, rev)
        mdot_in = mdot_in + flow_in
        mdot_out = mdot_out + flow_bf
        h_in_rate = h_in_rate + flow_in * _cp(ops.t_man) * ops.t_man

    if a_ex > 0.0:
        fwd = orifice_mass_flow(p, t, np.asarray(EXHAUST_BACKPRESSURE_PA), a_ex, R_GAS)
        rev = orifice_mass_flow(
            np.asarray(EXHAUST_BACKPRESSURE_PA),
            np.asarray(_EXHAUST_PORT_T_K),
            p,
            a_ex,
            R_GAS,
        )
        blowdown = p >= EXHAUST_BACKPRESSURE_PA
        flow_out = np.where(blowdown, fwd, 0.0)
        flow_rev = np.where(blowdown, 0.0, rev)
        mdot_out = mdot_out + flow_out
        mdot_in = mdot_in + flow_rev
        h_in_rate = h_in_rate + flow_rev * _cp(_EXHAUST_PORT_T_K) * _EXHAUST_PORT_T_K

    # Combustion heat release (analytic Wiebe derivative).
    if ops.combustion:
        x = (theta_rel - ops.soc_rel_deg) / ops.burn_deg
        a, mm = spec
        in_burn = (x > 0.0) & (x < 1.0)
        xc = np.clip(x, 1e-9, 1.0)
        dxb_dx = np.where(
            in_burn,
            a * (mm + 1.0) * xc**mm * np.exp(-a * xc ** (mm + 1.0)) / (1.0 - np.exp(-a)),
            0.0,
        )
        burn_rad = np.deg2rad(ops.burn_deg)
        dqc_dtheta = m_fuel * ops.lhv_j_kg * ops.comb_efficiency * dxb_dx / burn_rad
    else:
        dqc_dtheta = np.zeros_like(m)

    # Woschni heat loss (theta domain: divide the time rate by omega).
    if ops.heat_transfer:
        hw = woschni_h(p, t, tables.bore, ops.mean_piston_speed)
        dqh_dtheta = hw * a_w * (t - ops.wall_t_k) / omega
    else:
        dqh_dtheta = np.zeros_like(m)

    cv_t = _cv(t)
    cp_t = _cp(t)
    dm_dtheta = (mdot_in - mdot_out) / omega
    dh_in_dtheta = h_in_rate / omega
    dh_out_dtheta = mdot_out * cp_t * t / omega

    # m cv dT = dQc - dQh - p dV + (h_in - u dm_in) - outflow flow-work
    dt_dtheta = (
        dqc_dtheta
        - dqh_dtheta
        - p * dv
        + dh_in_dtheta
        - cv_t * t * (mdot_in / omega)
        - (mdot_out / omega) * R_GAS * t
    ) / np.maximum(m * cv_t, 1e-12)

    dw_dtheta = p * dv
    return dm_dtheta, dt_dtheta, p, dw_dtheta, dqc_dtheta, dqh_dtheta, dh_in_dtheta, dh_out_dtheta


# How often (in crank-angle steps) the integrator offers the pace hook a
# chance to yield/cancel. ~8 times per cycle at 1 deg resolution.
_PACE_EVERY_STEPS: int = 90


def run_cycles(
    tables: CycleTables,
    ops: OperatingPoints,
    wiebe_a: float,
    wiebe_m: float,
    max_cycles: int = 3,
    pace_hook=None,
) -> CycleResult:
    """March ``max_cycles`` full cycles; stop early once IMEP settles.

    ``pace_hook()`` is invoked every ~90 steps so a background bake can
    sleep briefly (yielding the core to the frame loop) or abort by
    raising — the cancellation path for stale bakes.
    """
    n = len(ops.rpm)
    omega = ops.rpm * (2.0 * np.pi / 60.0)  # rad/s

    # Mean piston speed needs the stroke; recover it from the tables'
    # displaced volume and bore.
    stroke = tables.v_displaced / (0.25 * np.pi * tables.bore**2)
    ops.mean_piston_speed = 2.0 * stroke * ops.rpm / 60.0

    h_rad = np.deg2rad(tables.step_deg)
    n_steps = len(tables.theta_rel) - 1
    spec = (wiebe_a, wiebe_m)

    # Initial state at IVC: manifold-density fill plus a hot residual guess.
    v0 = tables.volume[0]
    m = v0 * ops.p_man / (R_GAS * ops.t_man) * 1.02
    t = ops.t_man * 1.08
    m_residual = np.full(n, v0 * 0.12 * EXHAUST_BACKPRESSURE_PA / (R_GAS * _EXHAUST_PORT_T_K))

    imep_prev = np.zeros(n)
    result = None
    cycles_run = 0

    for cycle_i in range(max_cycles):
        if ops.two_stroke_trap_eff is not None:
            m_fresh = ops.two_stroke_trap_eff * m
        else:
            m_fresh = np.maximum(m - m_residual, _M_MIN_KG)
        if ops.ci_fuel_frac is not None:
            m_fuel = ops.ci_fuel_frac * m_fresh / ops.smoke_limit_afr
        else:
            m_fuel = m_fresh / ops.afr
        if not ops.combustion:
            m_fuel = np.zeros(n)

        work = np.zeros(n)
        q_comb = np.zeros(n)
        q_ht = np.zeros(n)
        h_in = np.zeros(n)
        h_out = np.zeros(n)
        p_max = np.zeros(n)
        u_start = m * _cv(t) * t

        for k in range(n_steps):
            if pace_hook is not None and k % _PACE_EVERY_STEPS == 0:
                pace_hook()
            d1 = _rhs(tables, k, m, t, ops, omega, m_fuel, spec)
            m_p = np.maximum(m + h_rad * d1[0], _M_MIN_KG)
            t_p = np.clip(t + h_rad * d1[1], _T_MIN_K, _T_MAX_K)
            d2 = _rhs(tables, k + 1, m_p, t_p, ops, omega, m_fuel, spec)

            m = np.maximum(m + 0.5 * h_rad * (d1[0] + d2[0]), _M_MIN_KG)
            t = np.clip(t + 0.5 * h_rad * (d1[1] + d2[1]), _T_MIN_K, _T_MAX_K)

            work += 0.5 * h_rad * (d1[3] + d2[3])
            q_comb += 0.5 * h_rad * (d1[4] + d2[4])
            q_ht += 0.5 * h_rad * (d1[5] + d2[5])
            h_in += 0.5 * h_rad * (d1[6] + d2[6])
            h_out += 0.5 * h_rad * (d1[7] + d2[7])
            p_max = np.maximum(p_max, d1[2])

            if k == tables.residual_index:
                m_residual = m.copy()

        cycles_run = cycle_i + 1
        imep = work / tables.v_displaced
        result = CycleResult(
            imep_pa=imep,
            p_max_pa=p_max,
            air_kg_per_cycle=m_fresh,
            fuel_kg_per_cycle=m_fuel,
            cycles_run=cycles_run,
            work_j=work,
            q_comb_j=q_comb,
            q_ht_j=q_ht,
            h_in_j=h_in,
            h_out_j=h_out,
            du_j=m * _cv(t) * t - u_start,
        )

        denom = np.maximum(np.abs(imep), 1e3)
        if cycle_i > 0 and np.all(np.abs(imep - imep_prev) / denom < _IMEP_CONVERGENCE):
            break
        imep_prev = imep

    return result
