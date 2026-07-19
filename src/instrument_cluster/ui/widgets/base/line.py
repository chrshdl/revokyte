import pygame

from ...colors import Color
from ...constants import HEADER_LINE_TOPLEFT
from ...utils import spos, su, sx, sy


class Line:
    def __init__(
        self,
        start_pos=HEADER_LINE_TOPLEFT,
        length=1280,
        color=Color.BLUE.rgb(),
        width=2,
        horizontal=True,
    ):
        """
        A simple widget that draws a straight line.

        Args:
            start_pos (tuple): (x, y) starting position of the line.
            length (int): Length of the line in pixels.
            color (tuple): RGB color of the line.
            width (int): Thickness of the line in pixels.
            horizontal (bool): True for horizontal, False for vertical.

        Coordinates are authored in design space and scaled to the active panel.
        """
        self.start_pos = spos(*start_pos)
        self.length = sx(length) if horizontal else sy(length)
        self.color = color
        self.width = max(1, su(width))
        self.horizontal = horizontal

    def draw(self, surface):
        """Draw the line on the given surface."""
        x, y = self.start_pos
        if self.horizontal:
            end_pos = (x + self.length, y)
        else:
            end_pos = (x, y + self.length)

        pygame.draw.line(surface, self.color, self.start_pos, end_pos, self.width)
