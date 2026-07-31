"""MappedEngineModel: the baked map wearing EngineModel's interface.

``ShiftLightController`` and ``ShiftPointCalculator`` only ever touch
``.redline`` and ``.get_torque(rpm)`` — this class provides exactly that
surface over a ``TorqueFuelMap``, so ``install_engine_map`` can swap it
in without either consumer changing.
"""

from __future__ import annotations

from .torque_map import TorqueFuelMap

# Beyond the baked axis, decay like the heuristic's over-rev branch
# (ecu.EngineModel): a quadratic drop of this fraction by redline.
_OVER_REV_TORQUE_DROP = 0.25


class MappedEngineModel:
    def __init__(
        self,
        torque_map: TorqueFuelMap,
        redline: float,
        on_redline_extend=None,
    ):
        self._map = torque_map
        self._redline = float(redline)
        # Called with the new value when telemetry raises the rev limit
        # past the baked axis — the service re-bakes with a longer axis
        # while this model keeps extrapolating.
        self._on_redline_extend = on_redline_extend

    @property
    def redline(self) -> float:
        return self._redline

    @redline.setter
    def redline(self, value: float) -> None:
        value = float(value)
        changed = value != self._redline
        self._redline = value
        if changed and value > self._map.rpm_max and self._on_redline_extend:
            self._on_redline_extend(value)

    def get_torque(self, rpm: float, throttle: float = 1.0) -> float:
        """Brake torque [Nm]; WOT column by default (what shift-point
        calculation wants), bilinear when a throttle is given."""
        if rpm > self._redline:
            return 0.0
        axis_max = self._map.rpm_max
        if rpm <= axis_max:
            if throttle >= 1.0:
                return self._map.wot_torque(rpm)
            return self._map.torque(rpm, throttle)

        # Above the baked axis (tuned rev limit, re-bake in flight):
        # decay from the last baked value like the heuristic does.
        edge = (
            self._map.wot_torque(axis_max)
            if throttle >= 1.0
            else self._map.torque(axis_max, throttle)
        )
        over_range = self._redline - axis_max
        if over_range <= 0.0:
            return max(0.0, edge)
        pct_past = (rpm - axis_max) / over_range
        return max(0.0, edge * (1.0 - _OVER_REV_TORQUE_DROP * pct_past**2))

    def get_fuel_flow(self, rpm: float, throttle: float) -> float:
        return self._map.fuel_flow(min(rpm, self._map.rpm_max), throttle)
