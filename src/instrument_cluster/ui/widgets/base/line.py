import pygame

from ...colors import Color


class Line:
    def __init__(
        self,
        start_pos: tuple[int, int],
        length: int,
        color=None,
        width: int = 2,
        horizontal: bool = True,
    ):
        """
        A simple widget that draws a straight line.

        Args:
            start_pos (tuple): (x, y) starting position of the line.
            length (int): Length of the line in pixels.
            color (tuple): RGB color of the line.
            width (int): Thickness of the line in pixels.
            horizontal (bool): True for horizontal, False for vertical.

        Coordinates are final (native) pixels — callers pass values from
        the active skin (see ``ui/views/header.py::header_line``).
        """
        self.start_pos = (round(start_pos[0]), round(start_pos[1]))
        self.length = round(length)
        self.color = Color.BLUE.rgb() if color is None else color
        self.width = max(1, width)
        self.horizontal = horizontal

    def draw(self, surface):
        """Draw the line on the given surface."""
        x, y = self.start_pos
        if self.horizontal:
            end_pos = (x + self.length, y)
        else:
            end_pos = (x, y + self.length)

        pygame.draw.line(surface, self.color, self.start_pos, end_pos, self.width)
