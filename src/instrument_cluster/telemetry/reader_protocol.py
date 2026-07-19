from typing import Protocol, runtime_checkable

from .models import TelemetryFrame


@runtime_checkable
class TelemetryReaderProtocol(Protocol):
    def start(self) -> None: ...
    def latest(self) -> TelemetryFrame | None: ...
    def stop(self) -> None: ...
