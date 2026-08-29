import math
from enum import Enum, auto

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]
ColorValues = RGB | RGBA

# Palette overrides — tooling only (the skin editor's live preview, tests).
# ``Color.rgb()`` consults this before the member's baked value, so a tool
# can restyle the palette at runtime and rebuild views to see the effect.
# The app itself never writes here; persisted palette changes are edits to
# this file (the skin editor rewrites it).
_overrides: dict["Color", ColorValues] = {}


def set_palette_override(color: "Color", rgb: ColorValues) -> None:
    """Tooling only: make ``color.rgb()`` return ``rgb`` in this process."""
    _overrides[color] = tuple(rgb)


def reset_palette_overrides() -> None:
    """Tooling only: drop every override set in this process."""
    _overrides.clear()


class Color(Enum):
    GREEN = (auto(), (0, 200, 0))
    DARK_GREEN = (auto(), (18, 136, 54))
    LIGHT_GREEN = (auto(), (80, 255, 120))
    YELLOW = (auto(), (200, 200, 0))
    DARK_YELLOW = (auto(), (136, 136, 0))
    BLACK = (auto(), (0, 0, 0))
    LIGHT_RED = (auto(), (250, 50, 50))
    LIGHTEST_RED = (auto(), (255, 80, 80))
    RED = (auto(), (200, 0, 0))
    DARK_RED = (auto(), (140, 30, 30))
    RPM_RED = (auto(), (225, 0, 45))
    RPM_DARK_RED = (auto(), (175, 30, 30))
    GREY = (auto(), (40, 40, 40))
    MEDIUM_GREY = (auto(), (10, 20, 30))
    DARK_GREY = (auto(), (30, 30, 30))
    DARKER_GREY = (auto(), (20, 20, 20))
    DARKEST_GREY = (auto(), (16, 16, 16))
    MID_GREY = (auto(), (70, 70, 70))
    LIGHT_GREY = (auto(), (120, 120, 120))
    LIGHTEST_GREY = (auto(), (128, 128, 128))
    DROPDOWN_LIGHT_GREY = (auto(), (60, 60, 60))
    BLUE = (auto(), (0, 110, 255))
    DARK_BLUE = (auto(), (0, 50, 125))
    DARKEST_BLUE = (auto(), (0, 3, 10))
    WHITE = (auto(), (210, 210, 210))
    # Measured off the 296 GT3 dash: its gear panel is a warm cream, not a
    # neutral grey, and sits at luminance 166 rather than WHITE's 210.
    # The 296 GT3's gear panel, measured off ferrari.com's own dash photo:
    # a neutral near-white that is BRIGHTER than WHITE (210), carrying a
    # gentle top-to-bottom ramp of roughly 196 -> 240.
    PANEL_WHITE = (auto(), (240, 240, 240))
    PANEL_WHITE_SHADOW = (auto(), (140, 140, 140))
    PANEL_OFF_WHITE = (auto(), (242, 242, 240))
    PANEL_LIGHT_GREY = (auto(), (205, 205, 205))
    PANEL_BEVEL_LIGHT = (auto(), (250, 250, 250))
    PANEL_BEVEL_DARK = (auto(), (96, 96, 96))
    PURPLE = (auto(), (200, 0, 200))
    LIGHT_PURPLE = (auto(), (185, 35, 135))
    MEDIUM_PURPLE = (auto(), (125, 50, 140))
    DEEP_PURPLE = (auto(), (90, 10, 165))
    ORANGE = (auto(), (255, 140, 0))

    def rgb(self) -> ColorValues:
        override = _overrides.get(self)
        return self.value[1] if override is None else override

    @classmethod
    def colormap(cls, f: float) -> ColorValues:
        """
        https://www.particleincell.com/2014/colormap/
        """
        a = (1 - f) * 5
        X = math.floor(a)
        Y = math.floor(255 * (a - X))
        match X:
            case 0:
                return (255, Y, 0)
            case 1:
                return (255 - Y, 255, 0)
            case 2:
                return (0, 255, Y)
            case 3:
                return (0, 255 - Y, 255)
            case 4:
                return (Y, 0, 255)
            case 5:
                return cls.PURPLE.rgb()
        raise NotImplementedError(f"colormap does not support input {f} yet.")
