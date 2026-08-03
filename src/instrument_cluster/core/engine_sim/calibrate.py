"""Staged calibration: fit one engine to its cars.json peaks.

Per pass (up to four, exited early by an acceptance probe that applies
the exact validation criteria to the current curve):

1. **displacement** — scales the whole curve to the torque target
   (torque is near-linear in displacement).
2. **ram_tune_rpm** — places the torque peak by damped secant, with the
   archetype-bounded ram gain escalating while the resonance bump loses
   to the VE droop (high-revving NA engines).
3. **joint ratio / roll-over** — the top-end value ratio (breathing on
   NA engines, wastegate compensation on boosted ones) and the power
   roll-over past rated speed (speed-dependent friction) are coupled:
   sequential stages spiral, so both update from a shared evaluation.
   The ratio only needs to land inside the span the correction blend
   can bridge, not at 1.0.

A final **correction** — a bounded (±5%) smooth blend — nails both DB
peak values exactly while preserving the simulated shape. Everything is
clamped; a car whose targets cannot be reached inside the clamps is
reported ``fit: failed`` and the runtime keeps the heuristic.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .archetypes import (
    EV_BYPASS,
    TEMPLATES,
    build_geometry,
    classify,
    fmep_prior,
)
from .engine import (
    EngineSimulator,
    FIT_MAX_CYCLES,
    FIT_STEP_DEG,
    FULL_MAX_CYCLES,
    FULL_STEP_DEG,
    correction_blend,
)
from .geometry import CylinderGeometry
from .params import EngineParams

# Knob bounds.
_DISPLACEMENT_L = (0.2, 9.0)
_DISPLACEMENT_L_2T = (0.05, 1.0)
_RAM_TUNE_MIN = 1200.0
_BREATHING = (0.22, 2.3)
_FMEP_SPEED_SCALE = (0.5, 3.5)
_CORRECTION = (0.95, 1.05)
# Physical sanity clamps. The BMEP cap is in *model* scale: the
# single-zone model runs ~25% optimistic on BMEP (the displacement fit
# absorbs it), so a real-world ~35 bar sanity line sits near 45 here.
_MAX_PISTON_SPEED = 32.0  # m/s at redline
_MAX_BMEP_PA = 45.0e5
# Acceptance. cars.json rpm values are round hundreds, so a location is
# only meaningful to a few hundred rpm; a crest flatter than the plateau
# tolerance has no meaningful location at all.
_VALUE_TOL = 0.02
_LOCATION_TOL_RPM = 350.0
_PLATEAU_TOL = 0.025

_OUTER_ITERS = 4  # max passes; an acceptance probe exits early
_PLACE_ITERS = 3
_FIT_AXIS_POINTS = 26


@dataclass
class FitOutcome:
    fit: str  # "ok" | "failed" | "ev_bypass"
    archetype: str
    params: EngineParams | None
    fit_error: dict


def _parabolic_peak(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Refine argmax with a parabola through its neighbours."""
    i = int(np.argmax(y))
    if i == 0 or i == len(x) - 1:
        return float(x[i]), float(y[i])
    denom = y[i - 1] - 2.0 * y[i] + y[i + 1]
    if abs(denom) < 1e-9:
        return float(x[i]), float(y[i])
    shift = 0.5 * (y[i - 1] - y[i + 1]) / denom
    shift = float(np.clip(shift, -1.0, 1.0))
    step = x[1] - x[0]
    peak_y = y[i] - 0.25 * (y[i - 1] - y[i + 1]) * shift
    return float(x[i] + shift * step), float(peak_y)


def _adapted_bore_stroke(template, displacement_l: float, redline: float) -> float:
    """Raise the template's bore/stroke ratio when the redline demands it:
    mean piston speed at redline is held under ~28 m/s (F1-style engines
    really are that oversquare)."""
    vd_cyl = displacement_l * 1e-3 / template.n_cyl
    stroke_max = 28.0 * 60.0 / (2.0 * redline)
    ratio_needed = float(np.sqrt(4.0 * vd_cyl / (np.pi * stroke_max**3)))
    return float(np.clip(max(template.bore_stroke_ratio, ratio_needed),
                         template.bore_stroke_ratio, 2.8))


def _build_params(
    template, displacement_l, ram_tune, breathing, fmep, redline, ram_gain
) -> EngineParams:
    if template.kind == "two_stroke":
        # Ports are cast into the cylinder wall; stretching them like a
        # cam grinds through the exhaust events. Scale areas only.
        cam = replace(
            template.cam,
            intake_area_frac=template.cam.intake_area_frac * breathing,
            exhaust_area_frac=template.cam.exhaust_area_frac * breathing,
        )
    else:
        cam = replace(
            template.cam,
            ivo_deg=template.cam.ivo_deg - 10.0 * (breathing - 1.0),
            ivc_deg=template.cam.ivc_deg + 20.0 * (breathing - 1.0),
            intake_area_frac=template.cam.intake_area_frac * breathing,
            exhaust_area_frac=template.cam.exhaust_area_frac * breathing,
        )
    geometry = build_geometry(template, displacement_l)
    geometry = replace(
        geometry,
        bore_stroke_ratio=_adapted_bore_stroke(template, displacement_l, redline),
    )
    return EngineParams(
        geometry=geometry,
        cam=cam,
        combustion=template.combustion,
        fmep=fmep,
        boost=template.boost,
        rated_rpm=redline,
        ram_tune_rpm=ram_tune,
        ram_gain=ram_gain,
        ram_low_penalty=1.2 * ram_gain,
    )


def _interp(axis, curve, rpm) -> float:
    return float(np.interp(rpm, axis, curve))


def _location_ok(
    axis, curve, target_rpm, end_rise_tol: float | None = None
) -> tuple[bool, float]:
    peak_rpm, peak_val = _parabolic_peak(axis, curve)
    err = peak_rpm - target_rpm
    if abs(err) <= _LOCATION_TOL_RPM:
        return True, err
    # Plateau escape: if the curve barely moves between its own peak and
    # the target rpm, the "location" is not meaningful (flat turbo
    # curves, restricted race engines).
    at_target = _interp(axis, curve, target_rpm)
    if peak_val > 0 and (peak_val - at_target) / peak_val <= _PLATEAU_TOL:
        return True, err
    # End-rise escape (power only): the source data cannot distinguish
    # "peaks at rated rpm" from "still pulling mildly at redline" — the
    # redline column is rated rpm + 1000 across the whole database. A
    # mild rise to the axis end is accepted; the shift consumer then
    # correctly shifts at redline for such engines.
    if (
        end_rise_tol is not None
        and float(curve[-1]) <= (1.0 + end_rise_tol) * at_target
    ):
        return True, err
    return False, err


def _assess(
    axis, torque, params, torque_target, rpm_t, torque_at_p_target,
    power_target_w, rpm_p, cap_nm: float | None = None,
):
    """Correction + validation criteria for one uncorrected curve.

    Returns (k_t, k_p, fit_error | None, ok); fit_error None means the
    curve is unusable (non-positive at a target point). ``cap_nm``
    applies the torque-limited-boost clip before validating.
    """
    model_t = _interp(axis, torque, rpm_t)
    model_p = _interp(axis, torque, rpm_p)
    if not np.isfinite(model_t) or model_t <= 1.0 or model_p <= 1.0:
        return 1.0, 1.0, None, False
    k_t = float(np.clip(torque_target / model_t, *_CORRECTION))
    k_p = float(np.clip(torque_at_p_target / model_p, *_CORRECTION))

    corrected = torque * correction_blend(
        {
            "k_torque": k_t,
            "k_power": k_p,
            "rpm_torque": rpm_t,
            "rpm_power": rpm_p,
        },
        axis,
    )
    if cap_nm is not None:
        corrected = np.minimum(corrected, cap_nm)
    power = corrected * axis * (2.0 * np.pi / 60.0)

    t_pct = _interp(axis, corrected, rpm_t) / torque_target - 1.0
    p_pct = _interp(axis, power, rpm_p) / power_target_w - 1.0
    t_ok, t_rpm_err = _location_ok(axis, corrected, rpm_t)
    p_ok, p_rpm_err = _location_ok(axis, power, rpm_p, end_rise_tol=0.06)

    fit_error = {
        "t_pct": round(t_pct, 4),
        "p_pct": round(p_pct, 4),
        "t_rpm": round(t_rpm_err, 1),
        "p_rpm": round(p_rpm_err, 1),
    }
    ok = (
        abs(t_pct) <= _VALUE_TOL and abs(p_pct) <= _VALUE_TOL and t_ok and p_ok
    )
    return k_t, k_p, fit_error, ok


def fit_car(car_id: int | str, specs: dict, overrides: dict) -> FitOutcome:
    archetype = classify(car_id, specs, overrides)
    if archetype == EV_BYPASS:
        return FitOutcome(EV_BYPASS, archetype, None, {})

    template = TEMPLATES[archetype]
    if template.boost is not None:
        # On boosted engines the torque-peak location is where boost
        # arrives, not where the runners resonate — anchor the spool to
        # the car's own torque peak, and stop wastegate compensation at
        # rated power so the power curve rolls over there.
        template = replace(
            template,
            boost=replace(
                template.boost,
                spool_rpm=0.55 * float(specs["max_torque_rpm"]),
                plateau_rpm=0.95 * float(specs["max_torque_rpm"]),
                comp_cap_rpm=float(specs["max_power_rpm"]),
            ),
        )
    torque_target = float(specs["max_torque_nm"])
    rpm_t = float(specs["max_torque_rpm"])
    power_target_w = float(specs["max_power_kw"]) * 1e3
    rpm_p = float(specs["max_power_rpm"])
    redline = float(specs["redline_rpm"])
    torque_at_p_target = power_target_w / (rpm_p * 2.0 * np.pi / 60.0)

    revs_per_cycle = 1.0 if template.kind == "two_stroke" else 2.0
    disp_bounds = (
        _DISPLACEMENT_L_2T if template.kind == "two_stroke" else _DISPLACEMENT_L
    )
    displacement = float(
        np.clip(
            2.0 * np.pi * revs_per_cycle * torque_target / template.bmep_ref_pa * 1e3,
            *disp_bounds,
        )
    )
    ram_tune = max(rpm_t, _RAM_TUNE_MIN)
    ram_gain = template.ram_gain_base
    breathing = float(np.clip(rpm_p / 5200.0, *_BREATHING))
    fmep_base = fmep_prior(redline)
    # One scalar on both speed-dependent friction terms: the knob that
    # rolls the power curve over past the rated speed.
    speed_scale = 1.0
    # The top-end "hold" knob: wastegate compensation on boosted engines,
    # charge sustain (the VVT equivalent) on NA ones. Same math — boost
    # or effective VE rising from the torque peak to rated power.
    boost_comp = template.boost.comp_per_krpm if template.boost else 0.0
    charge_comp = 0.0

    axis = np.linspace(max(900.0, 0.18 * redline), 1.03 * redline, _FIT_AXIS_POINTS)

    def current_fmep():
        return replace(
            fmep_base,
            c_pa_per_ms=fmep_base.c_pa_per_ms * speed_scale,
            d_pa_per_ms2=fmep_base.d_pa_per_ms2 * speed_scale,
        )

    def eval_curve(step=FIT_STEP_DEG, cycles=FIT_MAX_CYCLES):
        tpl = template
        if tpl.boost is not None:
            tpl = replace(tpl, boost=replace(tpl.boost, comp_per_krpm=boost_comp))
        params = _build_params(
            tpl, displacement, ram_tune, breathing, current_fmep(),
            redline, ram_gain,
        )
        if charge_comp > 0.0:
            params = replace(
                params,
                charge_comp_per_krpm=charge_comp,
                charge_comp_from_rpm=rpm_t,
                charge_comp_cap_rpm=rpm_p,
            )
        sim = EngineSimulator(params)
        torque = sim.simulate_wot(axis, step_deg=step, max_cycles=cycles,
                                  apply_correction=False)
        return params, torque

    # The fit axis is coarse (~240 rpm steps); chasing the peak tighter
    # than the parabola refinement can resolve just oscillates.
    axis_step = float(axis[1] - axis[0])
    place_tol = max(160.0, 0.65 * axis_step)

    def place_torque_peak():
        """Damped secant on ram_tune; returns the residual error."""
        nonlocal ram_tune
        prev = None
        err = 0.0
        for _ in range(_PLACE_ITERS + 1):
            _, torque = eval_curve()
            peak_rpm, _ = _parabolic_peak(axis, torque)
            err = rpm_t - peak_rpm
            if abs(err) < place_tol:
                break
            response = 0.9
            if prev is not None and abs(ram_tune - prev[0]) > 1.0:
                measured = (peak_rpm - prev[1]) / (ram_tune - prev[0])
                # A non-positive response means the peak is not tracking
                # the knob here (bump lost to the VE droop) — keep the
                # damped default instead of exploding the step.
                if measured > 0.05:
                    response = float(np.clip(measured, 0.15, 1.5))
            prev = (ram_tune, peak_rpm)
            step = float(np.clip(err / response, -1200.0, 1200.0))
            ram_tune = float(
                np.clip(ram_tune + step, _RAM_TUNE_MIN, 1.05 * redline)
            )
        return err

    def rescale_displacement():
        nonlocal displacement
        _, torque = eval_curve()
        model_at_t = _interp(axis, torque, rpm_t)
        if not np.isfinite(model_at_t) or model_at_t <= 1.0:
            raise ValueError("non-positive torque")
        displacement = float(
            np.clip(displacement * torque_target / model_at_t, *disp_bounds)
        )

    try:
        for _ in range(_OUTER_ITERS):
            # (a) displacement scales the whole curve to the torque target
            rescale_displacement()

            # (b) ram tuning places the torque peak; when the resonance
            # bump cannot beat the VE droop (high-revving NA engines),
            # escalate the ram gain — race intakes really are stronger.
            err = place_torque_peak()
            while abs(err) > 300.0 and ram_gain < template.ram_gain_max:
                ram_gain = min(ram_gain + 0.06, template.ram_gain_max)
                err = place_torque_peak()

            # (c) top-end ratio and power roll-over are a coupled pair —
            # sequential stages spiral (one destroys what the other just
            # fitted); joint updates from a shared evaluation converge.
            # The ratio only needs to reach the span the +-5% correction
            # blend can bridge (about 0.93..1.075), not 1.0 — demanding
            # more walks the fitter past perfectly valid states. On
            # boosted engines the ratio knob is wastegate compensation
            # (boost rising past the plateau); on NA engines, breathing.
            target_ratio = torque_at_p_target / torque_target
            if template.boost is not None:
                comp_span_krpm = max(
                    (rpm_p - template.boost.plateau_rpm) / 1000.0, 0.5
                )
            else:
                comp_span_krpm = max((rpm_p - rpm_t) / 1000.0, 0.5)
            for _ in range(_PLACE_ITERS + 1):
                _, torque = eval_curve()
                model_ratio = _interp(axis, torque, rpm_p) / max(
                    _interp(axis, torque, rpm_t), 1.0
                )
                ratio_off = target_ratio / max(model_ratio, 1e-3)

                # Drive friction off the *end-of-axis* rise past rated
                # power — the quantity validation actually gates on.
                power = torque * axis * (2.0 * np.pi / 60.0)
                overshoot = float(power[-1]) / max(
                    _interp(axis, power, rpm_p), 1.0
                )
                # Margin under the validation gate (1.06 at full
                # resolution): the fit profile reads slightly flatter.
                if 0.955 < ratio_off < 1.055 and overshoot < 1.035:
                    break
                comp_step = 0.9 * (ratio_off - 1.0) / comp_span_krpm
                if template.boost is not None:
                    floored = boost_comp <= 0.0 and comp_step < 0.0
                    boost_comp = float(np.clip(boost_comp + comp_step, 0.0, 0.4))
                else:
                    floored = charge_comp <= 0.0 and comp_step < 0.0
                    charge_comp = float(np.clip(charge_comp + comp_step, 0.0, 0.12))
                if floored:
                    # Model already too flat with the hold off — real
                    # droop is the breathing lever's job.
                    breathing = float(
                        np.clip(breathing * ratio_off**0.9, *_BREATHING)
                    )
                speed_scale = float(
                    np.clip(
                        speed_scale * min(overshoot, 1.3) ** 3.0,
                        *_FMEP_SPEED_SCALE,
                    )
                )

            # Acceptance probe: apply the exact validation criteria to
            # the current (fit-resolution) curve, correction included.
            # Passing exits the alternation; failing runs another pass,
            # which re-anchors whatever the ratio work just disturbed.
            params, torque = eval_curve()
            _, _, _, probe_ok = _assess(
                axis, torque, params, torque_target, rpm_t,
                torque_at_p_target, power_target_w, rpm_p,
            )
            if probe_ok:
                break

        # Shape is settled; put the absolute level back on target so the
        # bounded correction only has residuals to absorb.
        rescale_displacement()

        # Final full-resolution curve; correction nails the peak values.
        params, torque = eval_curve(step=FULL_STEP_DEG, cycles=FULL_MAX_CYCLES)
        k_t, k_p, fit_error, ok = _assess(
            axis, torque, params, torque_target, rpm_t,
            torque_at_p_target, power_target_w, rpm_p,
        )
        if fit_error is None:
            return FitOutcome("failed", archetype, None,
                              {"reason": "non-positive torque"})
        cap_nm = None
        if not ok:
            # Mid-span bulge rescue: heavily-boosted cars run
            # torque-limited boost control — the curve is clipped flat
            # at rated torque. Re-validate with the clip in place.
            cap_nm = 1.02 * max(torque_target, torque_at_p_target)
            k_t, k_p, fit_error, ok = _assess(
                axis, torque, params, torque_target, rpm_t,
                torque_at_p_target, power_target_w, rpm_p, cap_nm=cap_nm,
            )
        correction = {
            "k_torque": k_t,
            "k_power": k_p,
            "rpm_torque": rpm_t,
            "rpm_power": rpm_p,
        }
        if cap_nm is not None and ok:
            correction["cap_nm"] = round(cap_nm, 2)
        params = replace(params, correction=correction)

        geo = params.geometry
        cyl = CylinderGeometry(geo)
        piston_speed = float(cyl.mean_piston_speed(redline))
        bmep = (
            2.0 * np.pi * revs_per_cycle * torque_target
            / (geo.displacement_l * 1e-3)
        )
        ok = ok and piston_speed <= _MAX_PISTON_SPEED and bmep <= _MAX_BMEP_PA

        if not ok:
            return FitOutcome("failed", archetype, None, fit_error)
        return FitOutcome("ok", archetype, params, fit_error)

    except (FloatingPointError, ValueError, ZeroDivisionError) as exc:
        return FitOutcome("failed", archetype, None, {"reason": repr(exc)})
