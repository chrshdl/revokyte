"""The baked RPM x throttle torque/fuel map — the only engine-sim object
the 60 fps frame loop ever touches. Lookups are bilinear interpolation on
small float32 arrays: microseconds, no allocation of note."""

from __future__ import annotations

import numpy as np


class TorqueFuelMap:
    def __init__(
        self,
        rpm_axis: np.ndarray,
        throttle_axis: np.ndarray,
        torque_nm: np.ndarray,
        fuel_g_s: np.ndarray,
    ):
        self.rpm_axis = np.asarray(rpm_axis, dtype=np.float32)
        self.throttle_axis = np.asarray(throttle_axis, dtype=np.float32)
        self.torque_nm = np.asarray(torque_nm, dtype=np.float32)
        self.fuel_g_s = np.asarray(fuel_g_s, dtype=np.float32)

    @property
    def rpm_max(self) -> float:
        return float(self.rpm_axis[-1])

    def _bilinear(self, table: np.ndarray, rpm: float, throttle: float) -> float:
        thr_axis = self.throttle_axis
        throttle = min(max(throttle, float(thr_axis[0])), float(thr_axis[-1]))
        j = int(np.searchsorted(thr_axis, throttle))
        j = min(max(j, 1), len(thr_axis) - 1)
        t0, t1 = float(thr_axis[j - 1]), float(thr_axis[j])
        w = (throttle - t0) / (t1 - t0) if t1 > t0 else 0.0
        lo = float(np.interp(rpm, self.rpm_axis, table[:, j - 1]))
        hi = float(np.interp(rpm, self.rpm_axis, table[:, j]))
        return lo + w * (hi - lo)

    def torque(self, rpm: float, throttle: float = 1.0) -> float:
        return self._bilinear(self.torque_nm, rpm, throttle)

    def fuel_flow(self, rpm: float, throttle: float) -> float:
        """Fuel mass flow [g/s]; floored at zero (overrun cut)."""
        return max(0.0, self._bilinear(self.fuel_g_s, rpm, throttle))

    def wot_torque(self, rpm: float) -> float:
        return float(np.interp(rpm, self.rpm_axis, self.torque_nm[:, -1]))

    def to_dict(self) -> dict:
        return {
            "rpm_axis": self.rpm_axis.tolist(),
            "throttle_axis": self.throttle_axis.tolist(),
            "torque_nm": self.torque_nm.tolist(),
            "fuel_g_s": self.fuel_g_s.tolist(),
        }

    @staticmethod
    def from_dict(d: dict) -> "TorqueFuelMap":
        return TorqueFuelMap(
            np.asarray(d["rpm_axis"]),
            np.asarray(d["throttle_axis"]),
            np.asarray(d["torque_nm"]),
            np.asarray(d["fuel_g_s"]),
        )
