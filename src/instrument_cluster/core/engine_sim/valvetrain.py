"""Parametric valve (or port) flow areas and compressible orifice flow.

The cam is described only by its events and a peak effective area — the
lift lobe is a smooth ``sin(pi x)^p`` bump between opening and closing.
Volumetric efficiency is *not* prescribed anywhere: it emerges from these
areas fighting the piston through the orifice equation.
"""

from __future__ import annotations

import numpy as np

# Below this pressure ratio the orifice chokes (gamma ~ 1.35 average).
_GAMMA_FLOW: float = 1.35


def area_profile(
    theta_grid: np.ndarray,
    open_deg: float,
    close_deg: float,
    peak_area_m2: float,
    cycle_deg: float,
    shape_p: float = 0.8,
) -> np.ndarray:
    """Effective flow area (Cd*A) over an absolute crank-angle grid.

    Handles events that wrap around the cycle boundary (e.g. IVO at 350,
    IVC at 585 on a 720 cycle is fine; EVC past 720 wraps to 15).
    """
    duration = (close_deg - open_deg) % cycle_deg
    if duration <= 0.0:
        return np.zeros_like(theta_grid)
    x = ((theta_grid - open_deg) % cycle_deg) / duration
    lobe = np.where((x > 0.0) & (x < 1.0), np.sin(np.pi * np.clip(x, 0, 1)), 0.0)
    return peak_area_m2 * lobe**shape_p


def orifice_mass_flow(
    p_up: np.ndarray,
    t_up: np.ndarray,
    p_down: np.ndarray,
    area: np.ndarray,
    r_gas: float,
) -> np.ndarray:
    """Compressible flow through an effective area [kg/s], always >= 0.

    Caller decides direction by choosing which side is upstream.
    Subsonic below the critical ratio, choked above.
    """
    g = _GAMMA_FLOW
    pr_crit = (2.0 / (g + 1.0)) ** (g / (g - 1.0))
    pr = np.clip(p_down / np.maximum(p_up, 1.0), 0.0, 1.0)

    psi_choked = np.sqrt(g) * (2.0 / (g + 1.0)) ** ((g + 1.0) / (2.0 * (g - 1.0)))
    pr_sub = np.maximum(pr, pr_crit)
    psi_sub = pr_sub ** (1.0 / g) * np.sqrt(
        2.0 * g / (g - 1.0) * np.maximum(1.0 - pr_sub ** ((g - 1.0) / g), 0.0)
    )
    psi = np.where(pr <= pr_crit, psi_choked, psi_sub)

    return area * p_up / np.sqrt(r_gas * np.maximum(t_up, 1.0)) * psi
