from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # only for static checkers, not executed at runtime.
    from .state import State


class SupportsStateChange(ABC):
    @abstractmethod
    def change_state(self, next_state: State) -> None:
        pass
