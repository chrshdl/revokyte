from .signals.delta_calculator_protocol import DeltaCalculatorProtocol

# Re-export under the old name for any code that imports it from here.
DeltaCalculatorInterface = DeltaCalculatorProtocol


class DummyDeltaCalculator(DeltaCalculatorProtocol):
    def __init__(self) -> None:
        self._use_fastest_reference_only = False

    @property
    def use_fastest_reference_only(self) -> bool:
        return self._use_fastest_reference_only

    @use_fastest_reference_only.setter
    def use_fastest_reference_only(self, value: bool) -> None:
        self._use_fastest_reference_only = bool(value)

    def process(
        self, lap_index, dt, x, y, z, running,
        gt7_lap_time_ms=None, gt7_last_lap_time_ms=None,
    ) -> float | None:
        return None

    def full_reset(self) -> None:
        pass
