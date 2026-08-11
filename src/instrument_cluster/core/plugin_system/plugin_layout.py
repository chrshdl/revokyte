"""Layout context shared between the dashboard view and gauge plugins.

The bezel status LEDs (Setup toggle) reserve a strip at each screen edge;
both widget columns shift inward to make room. The strip width is the
single layout knob, and this dataclass is the one place the shifts are
derived — the view and every gauge plugin consume the same numbers, so
they can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutContext:
    """Immutable snapshot of the dashboard layout inputs.

    The strip width and shifts are per-skin values (native px for the
    active panel), read lazily so a LayoutContext built before the display
    profile is resolved still sees the right skin at use time.
    """

    status_lights: bool = False

    @property
    def shift_l(self) -> int:
        """Inward shift of the left widget column (native px)."""
        if not self.status_lights:
            return 0
        from ...ui.skins import active_skin

        return active_skin().dashboard.shift_l_on

    @property
    def shift_r(self) -> int:
        """Inward shift of the right widget column (native px)."""
        if not self.status_lights:
            return 0
        from ...ui.skins import active_skin

        return active_skin().dashboard.shift_r_on

    @classmethod
    def from_config(cls) -> "LayoutContext":
        from ...config import ConfigManager

        return cls(status_lights=ConfigManager.get_config().status_lights)
