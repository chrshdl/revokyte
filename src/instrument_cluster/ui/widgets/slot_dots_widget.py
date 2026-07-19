"""Page-indicator dots for the dashboard slot switcher.

Bottom-center chrome owned by DashboardView: one dot per available page
(the default layout plus every synced custom slot), the active page
filled. Hidden entirely while only one page exists, so free devices and
devices without synced layouts keep an untouched dashboard.
"""

import pygame
from pygame.sprite import DirtySprite

from ..colors import Color
from ..utils import spos, su

DOT_RADIUS = 5  # design px
DOT_PITCH = 26  # center-to-center distance, design px
CENTER_POS = (640, 700)  # design-space center of the dot row


class SlotDotsWidget(DirtySprite):
    system_widget = False

    def __init__(self):
        super().__init__()
        self._count = 1
        self._active = 0
        self._rebuild()

    def set_state(self, count: int, active: int) -> None:
        count = max(1, int(count))
        active = max(0, min(int(active), count - 1))
        if (count, active) == (self._count, self._active):
            return
        self._count, self._active = count, active
        self._rebuild()
        self.dirty = 1

    def _rebuild(self) -> None:
        r = su(DOT_RADIUS)
        pitch = su(DOT_PITCH)
        width = max(1, (self._count - 1) * pitch + 2 * r + 2)
        height = 2 * r + 2
        self.image = pygame.Surface((width, height), pygame.SRCALPHA)
        for i in range(self._count):
            color = (
                Color.WHITE.rgb() if i == self._active else Color.DARKER_GREY.rgb()
            )
            pygame.draw.circle(
                self.image, color, (r + 1 + i * pitch, height // 2), r
            )
        self.rect = self.image.get_rect(center=spos(*CENTER_POS))
        # One page = nothing to switch = no chrome.
        self.visible = 1 if self._count > 1 else 0

    def update(self, bus=None, dt: float = 0.0) -> None:
        """Static chrome — group-updated by the widget layer, nothing to do."""
