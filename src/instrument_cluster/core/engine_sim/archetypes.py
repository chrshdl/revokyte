"""Engine archetypes and the car classifier.

An archetype is a *shape prior*: cam events, compression, cylinder count,
friction character, boost. The calibrator re-fits displacement, ram
tuning, breathing and a bounded correction against the car's cars.json
peaks, so a misclassified archetype costs curve character, never the
calibrated peak values. Rotaries and two-strokes are mapped onto the
four-stroke integrator with equivalent parameters (documented on each
template) — again, only the shape depends on the approximation.

Classification: explicit per-car pins from tools/engine_sim/overrides.json
first, then name keywords (``name`` may be null), then spec-shape rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .params import BoostSpec, CamSpec, CombustionSpec, EngineGeometry, FmepSpec

EV_BYPASS = "ev_bypass"


@dataclass(frozen=True)
class ArchetypeTemplate:
    name: str
    n_cyl: int
    bore_stroke_ratio: float
    compression_ratio: float
    kind: str = "four_stroke"
    cam: CamSpec = field(
        default_factory=lambda: CamSpec(
            ivo_deg=348, ivc_deg=580, evo_deg=132, evc_deg=378
        )
    )
    combustion: CombustionSpec = field(default_factory=CombustionSpec)
    # Initial-displacement prior: Vd = 2*pi*revs_per_cycle * T / bmep_ref.
    bmep_ref_pa: float = 13.0e5
    boost: BoostSpec | None = None
    conrod_ratio: float = 3.3
    # Ram authority the fitter may use: intake/exhaust resonance strength
    # starts at base and escalates to max while the torque peak refuses
    # to move up (race intakes and tuned pipes really are that strong —
    # a chambered two-stroke pipe roughly doubles trapped charge).
    ram_gain_base: float = 0.10
    ram_gain_max: float = 0.25


_STREET_NA = ArchetypeTemplate(name="i4_na", n_cyl=4, bore_stroke_ratio=1.0,
                               compression_ratio=10.0)

TEMPLATES: dict[str, ArchetypeTemplate] = {
    "i4_na": _STREET_NA,
    # High-revving NA (VTEC and friends): long cam, big ports.
    "na_highrev": ArchetypeTemplate(
        name="na_highrev", n_cyl=4, bore_stroke_ratio=1.1,
        compression_ratio=11.0,
        cam=CamSpec(ivo_deg=340, ivc_deg=595, evo_deg=125, evc_deg=385,
                    intake_area_frac=0.10, exhaust_area_frac=0.078),
        ram_gain_base=0.15, ram_gain_max=0.55,
    ),
    "i6_na": ArchetypeTemplate(name="i6_na", n_cyl=6, bore_stroke_ratio=1.0,
                               compression_ratio=10.3),
    "turbo": ArchetypeTemplate(
        name="turbo", n_cyl=4, bore_stroke_ratio=0.98, compression_ratio=8.8,
        cam=CamSpec(ivo_deg=352, ivc_deg=575, evo_deg=135, evc_deg=372),
        bmep_ref_pa=17.0e5,
        boost=BoostSpec(peak_gauge_pa=0.8e5, spool_rpm=2600, plateau_rpm=4500),
    ),
    "turbo_six": ArchetypeTemplate(
        name="turbo_six", n_cyl=6, bore_stroke_ratio=1.0, compression_ratio=8.8,
        cam=CamSpec(ivo_deg=352, ivc_deg=575, evo_deg=135, evc_deg=372),
        bmep_ref_pa=17.0e5,
        boost=BoostSpec(peak_gauge_pa=0.85e5, spool_rpm=2800, plateau_rpm=4800),
    ),
    # Old-school two-valve pushrod V8: lazy cam, low compression, torque.
    "v8_pushrod": ArchetypeTemplate(
        name="v8_pushrod", n_cyl=8, bore_stroke_ratio=1.05,
        compression_ratio=9.5, conrod_ratio=3.4,
        cam=CamSpec(ivo_deg=352, ivc_deg=572, evo_deg=138, evc_deg=372,
                    intake_area_frac=0.075, exhaust_area_frac=0.058),
        bmep_ref_pa=11.5e5,
    ),
    "v8_dohc": ArchetypeTemplate(
        name="v8_dohc", n_cyl=8, bore_stroke_ratio=1.12,
        compression_ratio=11.0,
        cam=CamSpec(ivo_deg=344, ivc_deg=590, evo_deg=128, evc_deg=382,
                    intake_area_frac=0.095, exhaust_area_frac=0.074),
    ),
    "v12_exotic": ArchetypeTemplate(
        name="v12_exotic", n_cyl=12, bore_stroke_ratio=1.15,
        compression_ratio=11.0,
        cam=CamSpec(ivo_deg=342, ivc_deg=592, evo_deg=126, evc_deg=384,
                    intake_area_frac=0.10, exhaust_area_frac=0.078),
    ),
    # Race prototypes / Group C / VGT fantasy: everything oversized.
    "race_proto": ArchetypeTemplate(
        name="race_proto", n_cyl=8, bore_stroke_ratio=1.25,
        compression_ratio=12.0,
        cam=CamSpec(ivo_deg=336, ivc_deg=600, evo_deg=120, evc_deg=390,
                    intake_area_frac=0.115, exhaust_area_frac=0.09),
        bmep_ref_pa=14.0e5,
        ram_gain_base=0.15, ram_gain_max=0.40,
    ),
    # Wankel as a four-stroke equivalent: one rotor's face-sequence maps
    # to two equivalent cylinders at twice the nominal displacement
    # (a rotor fires every shaft rev, a four-stroke cylinder every other),
    # wide port-style "cam" with fat lobes, low equivalent compression.
    "rotary": ArchetypeTemplate(
        name="rotary", n_cyl=4, bore_stroke_ratio=1.2, compression_ratio=9.0,
        cam=CamSpec(ivo_deg=345, ivc_deg=600, evo_deg=120, evc_deg=380,
                    intake_area_frac=0.11, exhaust_area_frac=0.09,
                    shape_p=0.55),
        bmep_ref_pa=11.0e5,
        ram_gain_base=0.12, ram_gain_max=0.30,
    ),
    "diesel": ArchetypeTemplate(
        name="diesel", n_cyl=8, bore_stroke_ratio=0.94,
        compression_ratio=16.5,
        combustion=CombustionSpec(kind="ci", lhv_j_kg=42.8e6,
                                  burn_duration_deg=65.0,
                                  ca50_target_atdc_deg=10.0),
        bmep_ref_pa=18.0e5,
        boost=BoostSpec(peak_gauge_pa=1.6e5, spool_rpm=1800, plateau_rpm=3000),
    ),
    # Crankcase-scavenged racing two-stroke (the shifter kart): ports on
    # a 360 deg cycle, trapped charge via a fixed scavenging efficiency.
    "two_stroke": ArchetypeTemplate(
        name="two_stroke", n_cyl=1, bore_stroke_ratio=1.0,
        compression_ratio=8.0, kind="two_stroke",
        cam=CamSpec(ivo_deg=115, ivc_deg=245, evo_deg=95, evc_deg=265,
                    intake_area_frac=0.12, exhaust_area_frac=0.15,
                    shape_p=0.7),
        combustion=CombustionSpec(burn_duration_deg=42.0,
                                  comb_efficiency=0.88),
        bmep_ref_pa=9.0e5,
        ram_gain_base=0.45, ram_gain_max=1.0,
    ),
}

# Name keywords, first match wins (checked against the lowercased name).
_KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (EV_BYPASS, ("prius", "aqua s",)),
    ("rotary", ("rx-7", "rx-8", "rx500", "787b", "re amemiya", "rotary")),
    ("diesel", ("tdi", "hdi")),
    ("two_stroke", ("racing kart",)),
    ("v12_exotic", ("v12", "xj13", "250 gto", "330 p4", "365 gtb",
                    "512 bb", "countach", "miura", "aventador",
                    "murci", "veneno", "f1 '9", "f1 gtr", "zonda",
                    "one-77", "enzo", "laferrari")),
    ("v8_pushrod", ("camaro", "chevelle", "corvette", "stingray", "cobra",
                    "mustang", "viper", "challenger", "superbird",
                    "charger", "firebird", "g.t.350", "gt40",
                    "mark iv", "xnr")),
)


def _turbo_shaped(specs: dict) -> bool:
    """Flat, early torque with the power peak far above it. The power
    floor keeps small low-revving vintage engines (whose curves are flat
    for the opposite reason) out of the turbo bucket."""
    rpm_t = specs["max_torque_rpm"]
    rpm_p = specs["max_power_rpm"]
    torque_at_p = 9549.0 * specs["max_power_kw"] / rpm_p
    flatness = specs["max_torque_nm"] / max(torque_at_p, 1.0)
    if (
        specs["max_power_kw"] >= 90
        and rpm_t <= 3300
        and rpm_p >= rpm_t + 1800
        and flatness >= 1.10
    ):
        return True
    # Modern downsized turbos rate peak torque absurdly low (1500 rpm on
    # a GTI) — no NA engine peaks there.
    if (
        specs["max_power_kw"] >= 90
        and rpm_t <= 2000
        and rpm_p >= rpm_t + 2500
    ):
        return True
    # Heavily-boosted monsters (Veyron class): torque arrives so early
    # and stays so flat that the flatness ratio alone under-reads.
    return (
        specs["max_power_kw"] >= 300
        and rpm_t <= 3300
        and rpm_p >= rpm_t + 2500
    )


def classify(car_id: int | str, specs: dict, overrides: dict) -> str:
    pin = overrides.get(str(car_id))
    if pin:
        return pin

    name = (specs.get("name") or "").lower()
    for archetype, words in _KEYWORD_RULES:
        if any(w in name for w in words):
            return archetype

    kw = specs["max_power_kw"]
    rpm_p = specs["max_power_rpm"]

    turbo = _turbo_shaped(specs) or "turbo" in name
    if kw >= 480 and rpm_p >= 6500:
        return "race_proto"
    if turbo:
        return "turbo_six" if kw >= 240 else "turbo"
    if rpm_p >= 7600:
        return "na_highrev"
    if kw >= 300:
        return "v8_dohc"
    if kw >= 170:
        return "i6_na"
    return "i4_na"


def build_geometry(template: ArchetypeTemplate, displacement_l: float) -> EngineGeometry:
    return EngineGeometry(
        n_cyl=template.n_cyl,
        displacement_l=displacement_l,
        bore_stroke_ratio=template.bore_stroke_ratio,
        conrod_ratio=template.conrod_ratio,
        compression_ratio=template.compression_ratio,
        kind=template.kind,
    )


def fmep_prior(redline_rpm: float) -> FmepSpec:
    """Friction prior: high-revving engines are built lighter — scale the
    quadratic speed term down with redline so they stay alive up top."""
    d = min(260.0, max(30.0, 150.0 * (6500.0 / max(redline_rpm, 3000.0)) ** 2))
    return FmepSpec(d_pa_per_ms2=d)
