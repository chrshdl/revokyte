from __future__ import annotations

from enum import Enum
from importlib.resources import as_file, files

import pygame

from ..peripherals.display import scale_factors, scale_uniform

_font_cache: dict[tuple[FontFamily, int], pygame.font.Font] = {}


# ---------------------------------------------------------------------------
# Responsive scaling
#
# Widget geometry and font sizes are authored against the design resolution
# (1280x720, see display.py). These helpers map design values to the active
# panel's native logical size so the UI renders pixel-perfect on each display
# instead of being bitmap-scaled afterwards. Call them at widget/view
# construction time (after the display profile has been set).
# ---------------------------------------------------------------------------
def sx(value: float) -> int:
    """Scale an x-axis (horizontal) design value."""
    return round(value * scale_factors()[0])


def sy(value: float) -> int:
    """Scale a y-axis (vertical) design value."""
    return round(value * scale_factors()[1])


def su(value: float) -> int:
    """Scale a size/radius/gap uniformly (fonts, icons, square dimensions)."""
    return round(value * scale_uniform())


def srect(x: float, y: float, w: float, h: float) -> tuple[int, int, int, int]:
    """Scale a design-space rect (x, y, w, h)."""
    return (sx(x), sy(y), sx(w), sy(h))


def spos(x: float, y: float) -> tuple[int, int]:
    """Scale a design-space position (x, y)."""
    return (sx(x), sy(y))


def load_font(size: int, family: FontFamily) -> pygame.font.Font:
    # Fonts are authored in design pixels; scale to the active panel so text is
    # rendered at native resolution (crisp) rather than scaled after the fact.
    size = max(1, su(size))
    key = (family, size)
    if key in _font_cache:
        return _font_cache[key]

    font_res = files("instrument_cluster").joinpath(family.relpath)
    with as_file(font_res) as font_path:
        font = pygame.font.Font(str(font_path), size)

    _font_cache[key] = font
    return font


def load_image(relpath: str) -> pygame.Surface:
    """Load a bundled image asset (path relative to the package root)."""
    res = files("instrument_cluster").joinpath(relpath)
    with as_file(res) as path:
        return pygame.image.load(str(path))


class FontFamily(Enum):
    PIXEL_TYPE = ("pixeltype", "pixeltype")
    MATERIAL_SYMBOLS = ("material_symbols", "material-symbols-rounded-latin-300-normal")
    D_DIN_EXP_BOLD = ("d-din", "D-DINExp-Bold")
    D_DIN_EXP = ("d-din", "D-DINExp")
    D_DIN = ("d-din", "D-DIN")
    NOTOSANS_REGULAR = ("noto_sans", "NotoSans-Regular")
    NOTOSANS_LIGHT = ("noto_sans", "NotoSans-Light")
    NOTOSANS_EXTRA_LIGHT = ("noto_sans", "NotoSans-ExtraLight")

    APPLE_SYSTEM = ("Apple_System_1_Light", "apple-system-1-light")

    def __init__(self, subdir: str, basename: str):
        self.subdir = subdir  # folder under assets/fonts
        self.basename = basename  # filename without .ttf

    @property
    def relpath(self) -> str:
        return f"assets/fonts/{self.subdir}/{self.basename}.ttf"
