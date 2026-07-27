from typing import Protocol, runtime_checkable


@runtime_checkable
class DeltaCalculatorProtocol(Protocol):
    @property
    def use_fastest_reference_only(self) -> bool: ...

    @use_fastest_reference_only.setter
    def use_fastest_reference_only(self, value: bool) -> None: ...

    @property
    def has_reference(self) -> bool: ...

    def process(
        self,
        lap_index: int,
        dt: float,
        x: float,
        y: float,
        z: float,
        running: bool,
        gt7_lap_time_ms: int | None = None,
        gt7_last_lap_time_ms: int | None = None,
    ) -> float | None: ...

    def full_reset(self) -> None: ...
