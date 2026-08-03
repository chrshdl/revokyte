"""Wiebe heat release and ignition/injection timing.

Timing is anchored on a CA50 target (mass-fraction-burned 50% at
~8 deg ATDC), the standard MBT proxy — this replaces a per-cell MBT
search entirely: given the Wiebe shape and the rpm-scaled burn duration,
the start-of-combustion angle (spark/injection advance) follows in
closed form.
"""

from __future__ import annotations

import numpy as np

from .params import CombustionSpec


def burn_duration_deg(spec: CombustionSpec, rpm) -> np.ndarray:
    """Burn angle grows slowly with rpm (turbulence almost keeps up)."""
    rpm = np.asarray(rpm, dtype=float)
    return spec.burn_duration_deg * (np.maximum(rpm, 500.0) / 3000.0) ** spec.burn_rpm_exp


def _x50(spec: CombustionSpec) -> float:
    """Normalized burn coordinate where the (normalized) Wiebe hits 50%."""
    a, m = spec.wiebe_a, spec.wiebe_m
    norm = 1.0 - np.exp(-a)
    return float((-np.log(1.0 - 0.5 * norm) / a) ** (1.0 / (m + 1.0)))


def start_of_combustion_deg(spec: CombustionSpec, rpm) -> np.ndarray:
    """Absolute crank angle of burn start (< 720 means before TDC firing).

    theta_soc = ca50_target - x50 * duration, expressed relative to TDC
    firing at 0/720 deg. Returned in "signed ATDC" form: e.g. -22 means
    22 deg BTDC spark advance.
    """
    return spec.ca50_target_atdc_deg - _x50(spec) * burn_duration_deg(spec, rpm)


def wiebe_fraction(x, spec: CombustionSpec):
    """Normalized mass fraction burned over x in [0, 1]; exactly 1 at x=1."""
    a, m = spec.wiebe_a, spec.wiebe_m
    x = np.clip(x, 0.0, 1.0)
    return (1.0 - np.exp(-a * x ** (m + 1.0))) / (1.0 - np.exp(-a))


def afr_at_load(spec: CombustionSpec, throttle) -> np.ndarray:
    """SI mixture: stoichiometric at part load, enriched approaching WOT."""
    throttle = np.asarray(throttle, dtype=float)
    t = np.clip((throttle - 0.7) / 0.3, 0.0, 1.0)
    blend = t * t * (3.0 - 2.0 * t)
    return spec.afr_stoich - (spec.afr_stoich - spec.afr_wot) * blend
