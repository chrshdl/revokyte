"""Parameter dataclasses for the engine simulation.

Everything the integrator needs to describe one engine, plus (de)serialization
for the calibrated artifact ``db/engine_params.json``. The artifact is
generated offline by ``tools/engine_sim/fit_cars.py`` — the device never
fits, it only bakes maps from calibrated params.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Ambient/reference conditions shared by every engine.
P_AMBIENT_PA: float = 101_325.0
T_AMBIENT_K: float = 300.0
R_GAS: float = 287.0  # J/(kg K), charge treated as air
EXHAUST_BACKPRESSURE_PA: float = 1.05 * P_AMBIENT_PA
WALL_TEMPERATURE_K: float = 450.0
INTERCOOLER_DELTA_K: float = 25.0  # manifold heating on boosted engines


@dataclass(frozen=True)
class EngineGeometry:
    n_cyl: int
    displacement_l: float  # total swept volume
    bore_stroke_ratio: float  # bore / stroke
    conrod_ratio: float  # conrod length / crank radius (l/r)
    compression_ratio: float
    # "four_stroke" runs a 720 deg cycle; "two_stroke" a 360 deg cycle
    # (ports instead of valves). Rotaries are modelled as an equivalent
    # four-stroke (see archetypes.py) — the fitter re-scales displacement
    # so only the curve *shape* depends on the approximation.
    kind: str = "four_stroke"

    @property
    def cycle_deg(self) -> float:
        return 360.0 if self.kind == "two_stroke" else 720.0

    @property
    def revs_per_cycle(self) -> float:
        return 1.0 if self.kind == "two_stroke" else 2.0


@dataclass(frozen=True)
class CamSpec:
    """Valve events in absolute crank degrees, 0 = firing TDC.

    Four-stroke reference frame: BDC power 180, TDC overlap 360, BDC
    intake 540. Two-stroke ports use the same fields on a 360 deg cycle
    (exhaust ~ 95..265, transfer ~ 115..245).
    """

    ivo_deg: float
    ivc_deg: float
    evo_deg: float
    evc_deg: float
    # Peak effective (Cd*A) flow areas as a fraction of piston area.
    intake_area_frac: float = 0.085
    exhaust_area_frac: float = 0.065
    # Lift-lobe fatness: area(x) ~ sin(pi x)^shape_p, x in (0, 1).
    shape_p: float = 0.8


@dataclass(frozen=True)
class CombustionSpec:
    kind: str = "si"  # "si" | "ci"
    afr_wot: float = 12.6  # enriched at full load (SI)
    afr_stoich: float = 14.7
    lhv_j_kg: float = 44.0e6
    wiebe_a: float = 5.0
    wiebe_m: float = 2.0
    burn_duration_deg: float = 55.0  # at 3000 rpm reference
    burn_rpm_exp: float = 0.15  # duration ~ (rpm/3000)^exp
    ca50_target_atdc_deg: float = 8.0  # MBT proxy anchor
    comb_efficiency: float = 0.96
    smoke_limit_afr: float = 18.0  # CI fueling cap


@dataclass(frozen=True)
class BoostSpec:
    peak_gauge_pa: float
    spool_rpm: float
    plateau_rpm: float
    # Boost keeps rising past the plateau by this fraction per 1000 rpm —
    # how real wastegate control holds torque flat against VE/friction
    # droop. Fitted by the calibrator on flat-torque cars. Compensation
    # stops at comp_cap_rpm (rated power speed): past it the wastegate
    # holds, which is exactly why real turbo power curves peak there.
    comp_per_krpm: float = 0.0
    comp_cap_rpm: float | None = None


@dataclass(frozen=True)
class FmepSpec:
    """Chen-Flynn friction: fmep = a + b*p_max + c*S_p + d*S_p^2 [Pa]."""

    a_pa: float = 25_000.0
    b_of_pmax: float = 0.006
    c_pa_per_ms: float = 4_000.0
    d_pa_per_ms2: float = 150.0


@dataclass(frozen=True)
class EngineParams:
    geometry: EngineGeometry
    cam: CamSpec
    combustion: CombustionSpec
    fmep: FmepSpec
    boost: BoostSpec | None = None
    idle_rpm: float = 900.0
    # Rated speed used to size the throttle bore (WOT drop ~3% there).
    rated_rpm: float = 7000.0
    # Intake runner acoustics, the 1-D shortcut for inertia ram: charge
    # pressure at the valve is boosted near the tuned speed and penalized
    # well below it (quasi-static filling alone cannot produce the
    # mid-range VE peak every real engine has). ram_tune_rpm is the
    # calibrator's torque-peak-placement knob.
    ram_tune_rpm: float = 4500.0
    ram_gain: float = 0.10
    ram_low_penalty: float = 0.10
    # Charge sustain — the VVT / variable-intake equivalent of the turbo
    # path's wastegate compensation: modern engines hold volumetric
    # efficiency nearly flat between the torque and power peaks, which
    # quasi-static filling cannot reproduce. Charge pressure at the
    # valve rises by this fraction per 1000 rpm between
    # charge_comp_from_rpm and charge_comp_cap_rpm (fitted; 0 = off).
    charge_comp_per_krpm: float = 0.0
    charge_comp_from_rpm: float = 0.0
    charge_comp_cap_rpm: float | None = None
    # Multiplicative torque correction fitted by the calibrator: a smooth
    # blend from k_torque (at/below the torque peak) to k_power (at/above
    # the power peak) — bounded, monotone, no overshoot.
    correction: dict = field(
        default_factory=lambda: {
            "k_torque": 1.0,
            "k_power": 1.0,
            "rpm_torque": 3000.0,
            "rpm_power": 6000.0,
        }
    )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["boost"] = asdict(self.boost) if self.boost else None
        return d

    @staticmethod
    def from_dict(d: dict) -> "EngineParams":
        return EngineParams(
            geometry=EngineGeometry(**d["geometry"]),
            cam=CamSpec(**d["cam"]),
            combustion=CombustionSpec(**d["combustion"]),
            fmep=FmepSpec(**d["fmep"]),
            boost=BoostSpec(**d["boost"]) if d.get("boost") else None,
            idle_rpm=d.get("idle_rpm", 900.0),
            rated_rpm=d.get("rated_rpm", 7000.0),
            ram_tune_rpm=d.get("ram_tune_rpm", 4500.0),
            ram_gain=d.get("ram_gain", 0.10),
            ram_low_penalty=d.get("ram_low_penalty", 0.10),
            charge_comp_per_krpm=d.get("charge_comp_per_krpm", 0.0),
            charge_comp_from_rpm=d.get("charge_comp_from_rpm", 0.0),
            charge_comp_cap_rpm=d.get("charge_comp_cap_rpm"),
            correction=d.get("correction", {}),
        )


def load_params_db(path: Path) -> dict:
    """Load ``db/engine_params.json``: {car_id_str: entry}.

    Entry: {"archetype": str, "fit": "ok"|"failed"|"ev_bypass",
    "params": EngineParams dict | None, "fit_error": {...}}.
    Missing/corrupt file degrades to an empty db (runtime falls back to
    the heuristic EngineModel).
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}
