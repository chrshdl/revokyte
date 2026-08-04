from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .models import TelemetryFrame


@runtime_checkable
class TelemetryReaderProtocol(Protocol):
    def start(self) -> None: ...
    def latest(self) -> TelemetryFrame | None: ...
    def stop(self) -> None: ...
