"""Gas properties and in-cylinder heat transfer (Woschni)."""

from __future__ import annotations

import numpy as np

from .params import R_GAS

# gamma(T): linear fall from cold air toward hot burned gas, clamped.
_GAMMA_COLD: float = 1.40
_GAMMA_SLOPE_PER_K: float = 6.0e-5
_GAMMA_MIN: float = 1.26

# Woschni: h = C * B^-0.2 * p^0.8 * T^-0.55 * w^0.8  (p in kPa, h in W/m^2K)
_WOSCHNI_C: float = 3.26
_WOSCHNI_C1: float = 2.28  # gas velocity ~ C1 * mean piston speed


def gamma(t_k):
    return np.clip(
        _GAMMA_COLD - _GAMMA_SLOPE_PER_K * (np.asarray(t_k, dtype=float) - 300.0),
        _GAMMA_MIN,
        _GAMMA_COLD,
    )


def cv(t_k):
    return R_GAS / (gamma(t_k) - 1.0)


def cp(t_k):
    g = gamma(t_k)
    return g * R_GAS / (g - 1.0)


def woschni_h(p_pa, t_k, bore_m, mean_piston_speed):
    """Convective heat-transfer coefficient [W/(m^2 K)]."""
    w = _WOSCHNI_C1 * mean_piston_speed
    return (
        _WOSCHNI_C
        * bore_m**-0.2
        * (np.maximum(p_pa, 1.0) / 1000.0) ** 0.8
        * np.maximum(t_k, 1.0) ** -0.55
        * np.maximum(w, 0.1) ** 0.8
    )
