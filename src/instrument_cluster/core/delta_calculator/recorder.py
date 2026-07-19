"""Telemetry capture with distance-based filtering."""

from __future__ import annotations

from typing import List, Optional

import numpy as np


class LapRecorder:
    """
    Records telemetry points with distance-based filtering.

    Points are only recorded when they are between *min_step_m* and
    *max_step_m* from the last recorded point.  If the car jumps more
    than *max_step_m* (teleport, running=False gap, telemetry dropout)
    the point is skipped but ``_last_pos`` is still advanced so that
    recording can resume on the very next frame.
    """

    def __init__(self, min_step_m: float, max_step_m: float):
        self._min_step_sq = float(min_step_m) ** 2
        self._max_step_sq = float(max_step_m) ** 2
        self._xs: List[float] = []
        self._ys: List[float] = []
        self._zs: List[float] = []
        self._times: List[float] = []
        self._last_pos: Optional[np.ndarray] = None

    # -- public API ----------------------------------------------------------

    def reset(self) -> None:
        """Clear all recorded data and position tracking."""
        self._xs.clear()
        self._ys.clear()
        self._zs.clear()
        self._times.clear()
        self._last_pos = None

    def record(self, x: float, y: float, z: float, lap_time: float) -> bool:
        """
        Attempt to record a telemetry point.

        Returns True if the point was accepted, False if it was filtered
        (too close or too far from the previous accepted point).
        """
        pos = np.array([x, y, z])

        # First point of the lap — always accept
        if self._last_pos is None:
            self._last_pos = pos
            self._append(x, y, z, lap_time)
            return True

        d2 = float(np.sum((pos - self._last_pos) ** 2))

        if d2 > self._max_step_sq:
            # Too far (teleport / gap).  Skip the point but advance
            # _last_pos so that the next frame can be evaluated from
            # the car's actual position.  Without this, _last_pos
            # stays frozen and ALL subsequent points are rejected for
            # the rest of the lap.
            self._last_pos = pos
            return False

        if d2 >= self._min_step_sq:
            # Good distance — record
            self._last_pos = pos
            self._append(x, y, z, lap_time)
            return True

        # Too close — skip (position unchanged so gap keeps growing
        # until min_step_m is reached).
        return False

    # -- data access ---------------------------------------------------------

    @property
    def point_count(self) -> int:
        return len(self._xs)

    @property
    def has_data(self) -> bool:
        return len(self._xs) >= 2

    @property
    def xs(self) -> List[float]:
        return self._xs

    @property
    def ys(self) -> List[float]:
        return self._ys

    @property
    def zs(self) -> List[float]:
        return self._zs

    @property
    def times(self) -> List[float]:
        return self._times

    # -- internals -----------------------------------------------------------

    def _append(self, x: float, y: float, z: float, lap_time: float) -> None:
        self._xs.append(x)
        self._ys.append(y)
        self._zs.append(z)
        self._times.append(lap_time)
