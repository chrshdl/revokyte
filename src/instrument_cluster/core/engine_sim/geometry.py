"""Slider-crank kinematics: cylinder volume and wall area vs crank angle."""

from __future__ import annotations

import numpy as np

from .params import EngineGeometry


class CylinderGeometry:
    """Per-cylinder V(theta), dV/dtheta and heat-transfer area.

    theta is in degrees with 0 at firing TDC; derivatives are per *radian*
    so they plug straight into the time-domain first law
    (d/dt = omega * d/dtheta).
    """

    def __init__(self, geo: EngineGeometry):
        self.geo = geo
        vd_total = geo.displacement_l * 1e-3  # m^3
        self.v_displaced = vd_total / geo.n_cyl
        # Vd = (pi/4) B^2 S with B/S = bore_stroke_ratio
        self.bore = (4.0 * self.v_displaced * geo.bore_stroke_ratio / np.pi) ** (
            1.0 / 3.0
        )
        self.stroke = self.bore / geo.bore_stroke_ratio
        self.piston_area = 0.25 * np.pi * self.bore**2
        self.crank_radius = self.stroke / 2.0
        self.conrod = geo.conrod_ratio * self.crank_radius
        self.v_clearance = self.v_displaced / (geo.compression_ratio - 1.0)

    def piston_travel(self, theta_deg):
        """Distance of the piston from TDC [m]."""
        th = np.deg2rad(np.asarray(theta_deg, dtype=float))
        r, l = self.crank_radius, self.conrod
        return r * (1.0 - np.cos(th)) + l * (
            1.0 - np.sqrt(1.0 - (r / l * np.sin(th)) ** 2)
        )

    def volume(self, theta_deg):
        return self.v_clearance + self.piston_area * self.piston_travel(theta_deg)

    def dvolume_dtheta(self, theta_deg):
        """dV/dtheta [m^3 / rad]."""
        th = np.deg2rad(np.asarray(theta_deg, dtype=float))
        r, l = self.crank_radius, self.conrod
        lam = r / l
        sin_t, cos_t = np.sin(th), np.cos(th)
        return (
            self.piston_area
            * r
            * sin_t
            * (1.0 + lam * cos_t / np.sqrt(1.0 - (lam * sin_t) ** 2))
        )

    def wall_area(self, theta_deg):
        """Exposed head + piston crown + liner area [m^2]."""
        return 2.0 * self.piston_area + np.pi * self.bore * self.piston_travel(
            theta_deg
        )

    def mean_piston_speed(self, rpm):
        """S_p = 2 * stroke * N [m/s]."""
        return 2.0 * self.stroke * np.asarray(rpm, dtype=float) / 60.0
