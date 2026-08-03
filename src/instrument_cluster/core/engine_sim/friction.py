"""Chen-Flynn rubbing friction. Pumping losses are already inside the
net IMEP (the integrator runs the full 720 deg including gas exchange),
so brake = indicated(net) - fmep."""

from __future__ import annotations

import numpy as np

from .params import FmepSpec


def fmep_pa(spec: FmepSpec, p_max_pa, mean_piston_speed) -> np.ndarray:
    s_p = np.asarray(mean_piston_speed, dtype=float)
    return (
        spec.a_pa
        + spec.b_of_pmax * np.asarray(p_max_pa, dtype=float)
        + spec.c_pa_per_ms * s_p
        + spec.d_pa_per_ms2 * s_p**2
    )
