"""Physics identities of the crank-angle engine model.

These pin the *model*, not any particular car: kinematic volume
identities, thermodynamic limits (Otto efficiency with losses removed),
first-law closure over a converged cycle, convergence behaviour and
step-size independence.
"""

import numpy as np
import pytest

from instrument_cluster.core.engine_sim.combustion import (
    start_of_combustion_deg,
    wiebe_fraction,
)
from instrument_cluster.core.engine_sim.cycle import (
    OperatingPoints,
    build_tables,
    run_cycles,
)
from instrument_cluster.core.engine_sim.engine import EngineSimulator
from instrument_cluster.core.engine_sim.geometry import CylinderGeometry
from instrument_cluster.core.engine_sim.params import (
    CamSpec,
    CombustionSpec,
    EngineGeometry,
    EngineParams,
    FmepSpec,
)
from instrument_cluster.core.engine_sim.valvetrain import area_profile


@pytest.fixture
def i4_geometry():
    return EngineGeometry(
        n_cyl=4,
        displacement_l=2.0,
        bore_stroke_ratio=1.0,
        conrod_ratio=3.3,
        compression_ratio=10.0,
    )


@pytest.fixture
def i4_params(i4_geometry):
    return EngineParams(
        geometry=i4_geometry,
        cam=CamSpec(ivo_deg=350, ivc_deg=585, evo_deg=135, evc_deg=375),
        combustion=CombustionSpec(),
        fmep=FmepSpec(),
        rated_rpm=7000,
    )


# --- kinematics ---


def test_volume_identities(i4_geometry):
    cyl = CylinderGeometry(i4_geometry)
    vd = 2.0e-3 / 4

    # TDC traps exactly the clearance volume; BDC adds the swept volume.
    assert cyl.volume(0.0) == pytest.approx(cyl.v_clearance, rel=1e-9)
    assert cyl.volume(180.0) == pytest.approx(cyl.v_clearance + vd, rel=1e-9)
    # Compression ratio is V(BDC)/V(TDC) by definition.
    assert cyl.volume(180.0) / cyl.volume(0.0) == pytest.approx(10.0, rel=1e-9)


def test_dvolume_matches_numeric_derivative(i4_geometry):
    cyl = CylinderGeometry(i4_geometry)
    theta = np.linspace(0.0, 720.0, 1441)
    v = cyl.volume(theta)
    dv_numeric = np.gradient(v, np.deg2rad(theta))
    dv_analytic = cyl.dvolume_dtheta(theta)
    assert np.allclose(dv_analytic[2:-2], dv_numeric[2:-2], atol=2e-7)


# --- valvetrain ---


def test_valve_area_zero_outside_events():
    theta = np.arange(0.0, 720.0, 1.0)
    area = area_profile(theta, 350.0, 585.0, 1e-3, 720.0)
    window = ((theta - 350.0) % 720.0) < (585.0 - 350.0)
    assert np.all(area[~window] == 0.0)
    assert np.all(area[window & (theta > 351) & (theta < 584)] > 0.0)
    assert area.max() == pytest.approx(1e-3, rel=1e-2)


def test_valve_area_wraps_across_cycle_boundary():
    theta = np.arange(0.0, 720.0, 1.0)
    area = area_profile(theta, 700.0, 60.0, 1e-3, 720.0)  # EVC past TDC
    assert area[int(710)] > 0.0
    assert area[int(30)] > 0.0
    assert area[int(400)] == 0.0


# --- combustion ---


def test_wiebe_fraction_normalized():
    spec = CombustionSpec()
    assert wiebe_fraction(0.0, spec) == 0.0
    assert wiebe_fraction(1.0, spec) == pytest.approx(1.0, abs=1e-12)
    x = np.linspace(0, 1, 100)
    assert np.all(np.diff(wiebe_fraction(x, spec)) >= 0.0)


def test_advance_grows_with_rpm():
    """Burn duration grows with rpm, so the CA50 anchor demands more
    spark advance (more negative start of combustion)."""
    spec = CombustionSpec()
    soc = start_of_combustion_deg(spec, np.array([1500.0, 7000.0]))
    assert soc[1] < soc[0] < 0.0


# --- cycle thermodynamics ---


def _single_op(rpm=3000.0, p_man=95_000.0):
    # The sweep is anchored at IVC (585 deg abs), so TDC firing lands at
    # sweep-relative (720 - 585) = 135 deg; ~20 deg BTDC spark is 115.
    return OperatingPoints(
        rpm=np.array([rpm]),
        p_man=np.array([p_man]),
        t_man=np.array([300.0]),
        soc_rel_deg=np.array([115.0]),
        burn_deg=np.array([55.0]),
        afr=np.array([12.6]),
    )


def test_motored_cycle_net_work_is_small_negative(i4_params):
    """Combustion off: compression work comes back in expansion minus
    heat/pumping/leakage losses — net indicated work must be slightly
    negative, never positive."""
    cyl = CylinderGeometry(i4_params.geometry)
    tables = build_tables(cyl, i4_params.cam, 1.0)
    ops = _single_op()
    ops.combustion = False
    res = run_cycles(tables, ops, 5.0, 2.0, max_cycles=3)
    assert res.imep_pa[0] < 0.0
    assert res.imep_pa[0] > -1.5e5  # losses, not an explosion


def test_ideal_limit_approaches_otto_efficiency(i4_params):
    """Heat transfer off, near-instant burn at TDC: indicated efficiency
    must land in the neighbourhood of the air-standard Otto value for an
    effective (temperature-averaged) gamma."""
    cyl = CylinderGeometry(i4_params.geometry)
    tables = build_tables(cyl, i4_params.cam, 0.5)
    ops = _single_op()
    ops.heat_transfer = False
    ops.soc_rel_deg = np.array([133.0])  # burn centred tight at TDC (135)
    ops.burn_deg = np.array([12.0])
    res = run_cycles(tables, ops, 5.0, 2.0, max_cycles=4)

    eta = res.work_j[0] / res.q_comb_j[0]
    # gamma spans ~1.40 cold to ~1.26 hot; Otto bounds for rc=10:
    #   1 - rc^(1-gamma) in [0.45, 0.60]. The open cycle also pays
    #   exhaust enthalpy, so demand the broad corridor, not a point.
    assert 0.40 < eta < 0.62


def test_first_law_closure(i4_params):
    """Over a converged cycle: Q_comb - Q_ht - W - (H_out - H_in) ~ dU ~ 0."""
    cyl = CylinderGeometry(i4_params.geometry)
    tables = build_tables(cyl, i4_params.cam, 1.0)
    res = run_cycles(tables, _single_op(), 5.0, 2.0, max_cycles=4)

    residual = (
        res.q_comb_j[0]
        - res.q_ht_j[0]
        - res.work_j[0]
        - (res.h_out_j[0] - res.h_in_j[0])
        - res.du_j[0]
    )
    # Tolerance covers the cv(T)-approximation: the ODE integrates
    # du = cv(T) dT while the bookkeeping states u = cv(T)*T, and the
    # difference (the T*dcv/dT term) is worth a few percent of Q over a
    # 2000 K swing. A sign error or missing term shows up far larger.
    assert abs(residual) < 0.08 * res.q_comb_j[0]


def test_cycles_converge(i4_params):
    cyl = CylinderGeometry(i4_params.geometry)
    tables = build_tables(cyl, i4_params.cam, 1.0)
    res = run_cycles(tables, _single_op(), 5.0, 2.0, max_cycles=6)
    assert res.cycles_run <= 4


def test_step_size_independence(i4_params):
    """1.0 deg must sit within 1% of a 0.25 deg reference."""
    sim = EngineSimulator(i4_params)
    rpms = np.array([2500.0, 5000.0])
    coarse = sim.simulate_wot(rpms, step_deg=1.0, max_cycles=4)
    fine = sim.simulate_wot(rpms, step_deg=0.25, max_cycles=4)
    assert np.all(np.abs(coarse - fine) / np.abs(fine) < 0.01)


# --- simulator-level behaviour ---


def test_torque_increases_with_throttle(i4_params):
    sim = EngineSimulator(i4_params)
    torque, _ = sim.simulate_grid(
        np.array([3000.0]), np.array([0.2, 0.5, 1.0]), step_deg=2.0
    )
    assert torque[0, 0] < torque[0, 1] < torque[0, 2]


def test_fuel_flow_positive_and_rises_with_load(i4_params):
    sim = EngineSimulator(i4_params)
    _, fuel = sim.simulate_grid(
        np.array([3000.0, 6000.0]), np.array([0.3, 1.0]), step_deg=2.0
    )
    assert np.all(fuel > 0.0)
    assert fuel[0, 1] > fuel[0, 0]
    assert fuel[1, 1] > fuel[0, 1]


def test_ram_tuning_moves_torque_peak(i4_params):
    from dataclasses import replace

    # Tunes chosen inside the regime where the resonance bump outweighs
    # the quasi-static VE droop; the calibrator couples this knob with
    # valve-area scaling for high-revving engines.
    rpms = np.arange(1500.0, 7100.0, 250.0)
    low = EngineSimulator(replace(i4_params, ram_tune_rpm=2500.0))
    high = EngineSimulator(replace(i4_params, ram_tune_rpm=4200.0))
    peak_low = rpms[np.argmax(low.simulate_wot(rpms))]
    peak_high = rpms[np.argmax(high.simulate_wot(rpms))]
    assert peak_high > peak_low
