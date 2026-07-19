"""Backward-compatible facade.

The delta calculator used to live in this single module. It is now split by
responsibility across :mod:`~delta_calculator.projection`,
:mod:`~delta_calculator.recorder`, :mod:`~delta_calculator.reference` and
:mod:`~delta_calculator.calculator`. This module re-exports the public names so
existing imports (``from delta_calculator.core import DeltaCalculator``) keep
working unchanged.
"""

from __future__ import annotations

from .calculator import DeltaCalculator
from .projection import ProjectionResult, ReferenceTrajectory
from .recorder import LapRecorder
from .reference import ReferenceManager

__all__ = [
    "DeltaCalculator",
    "LapRecorder",
    "ProjectionResult",
    "ReferenceManager",
    "ReferenceTrajectory",
]
