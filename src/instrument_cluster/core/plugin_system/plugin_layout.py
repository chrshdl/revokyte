"""Layout context shared between the dashboard view and gauge plugins.

The bezel status LEDs (Setup toggle) reserve a strip at each screen edge;
both widget columns shift inward to make room. The strip width is the
single layout knob, and this dataclass is the one place the shifts are
derived — the view and every gauge plugin consume the same numbers, so
they can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass

# Design-space width of the strip reserved at each screen edge for the
# bezel status LEDs (StatusLightsWidget).
STATUS_STRIP_W = 100


@dataclass(frozen=True)
class LayoutContext:
    """Immutable snapshot of the dashboard layout inputs."""

    status_lights: bool = False

    @property
    def shift_l(self) -> int:
        """Inward shift of the left widget column (design px)."""
        return STATUS_STRIP_W - 10 if self.status_lights else 0

    @property
    def shift_r(self) -> int:
        """Inward shift of the right widget column (design px)."""
        return STATUS_STRIP_W - 18 if self.status_lights else 0

    @classmethod
    def from_config(cls) -> "LayoutContext":
        from ...config import ConfigManager

        return cls(status_lights=ConfigManager.get_config().status_lights)
