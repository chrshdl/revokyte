"""Standalone gear indicator in the style of the Ferrari 296 GT3 Evo wheel dash.

A single-file, dependency-free (pygame only) widget: a glossy white panel with a
big near-black gear character. Nothing here imports the instrument_cluster
package, so the file can be copied out and used on its own.

    panel = FerrariGearPanel(310, 335)
    panel.set_value(3)
    panel.draw(screen, center=(640, 360))

Run it directly for a live demo:

    python tools/ferrari_gear_panel.py                 # interactive window
    python tools/ferrari_gear_panel.py --vector        # force the vector "0"
    python tools/ferrari_gear_panel.py --shot /tmp/gear.png --value 0

Keys in the demo: UP/DOWN or 0-9 set the gear, N/R/P the named positions,
V toggles the vector renderer, S saves a PNG, ESC quits.
"""

from __future__ import annotations

import argparse
import os
import sys

import pygame

# --- reference measurements -------------------------------------------------
# Every number below is a ratio of the panel's own width or height, so the
# widget is resolution independent: the 310x335 default is just one sample of
# it. Ratios are as measured off the reference photo of the wheel dash.

ASPECT = 0.925  # width / height
RADIUS_W = 0.065  # corner radius
BORDER_W = 0.012  # outer stroke, min 2px
SHADOW_OFF_H = 0.010  # drop shadow y offset
SHADOW_BLUR_W = 0.030  # drop shadow blur radius
SHADOW_ALPHA = 0.35
CAP_HEIGHT_H = 0.62  # glyph cap height
OPTICAL_RISE_H = 0.015  # nudge the glyph up off the true centre

# Vector fallback "0": a thick-stroked rounded rectangle ring, not an oval.
VEC_W = 0.42  # outer width  (of panel width)
VEC_H = 0.62  # outer height (of panel height)
VEC_STROKE_W = 0.085  # ring thickness
VEC_RADIUS_W = 0.10  # ring corner radius

# --- the bevel --------------------------------------------------------------
# The panel is not a flat white swatch with a highlight on top: it is a white
# plateau with the light falling off into every edge, and the top fall-off is
# far longer than the others. That long, decelerating ramp down the top of the
# panel is the whole trick -- the eye reads a slope it can't see the end of as a
# surface tilting away, so the top of the tile becomes a "roof".
#
# Both ramps below are sampled off the reference photo and lifted so the plateau
# lands on white instead of the photo's 241. Stops are (fraction, grey).

# Down the panel: roof at the top, plateau from ~80%, short lip at the bottom.
FACE_V_STOPS = (
    (0.000, 110),  # contact shadow, mostly hidden by the stroke
    (0.012, 132),
    (0.028, 172),
    (0.045, 190),
    (0.065, 202),
    (0.100, 216),
    (0.150, 229),  # roof still climbing hard here
    (0.210, 237),
    (0.265, 241),
    (0.375, 246),
    (0.480, 250),
    (0.640, 253),
    (0.810, 255),  # plateau
    (0.950, 253),
    (0.982, 245),
    (1.000, 224),  # bottom lip
)

# Across the panel: the side walls, as a multiplier mirrored about the centre.
# Positions are fractions of the *full* width, so the wall is ~6% either side.
# 255 leaves the face untouched, which is what the middle 88% gets.
FACE_H_STOPS = (
    (0.000, 105),
    (0.012, 165),
    (0.020, 196),
    (0.030, 220),
    (0.042, 238),
    (0.055, 250),
    (0.070, 255),
    (0.500, 255),
)

# Two rim lines, both faded out down the panel. The inner one sits just inside
# the stroke and reads as the lip the roof folds away from -- in the reference
# it is a soft ~200 grey rather than a white pinstripe, so the alpha stays low.
# The outer one rides the very edge of the stroke: a hard specular on the
# machined corner, and the reason the tile looks raised off its surround.
RIM_W = 0.0060  # inner highlight width, fraction of panel width
RIM_COLOR = (255, 255, 255)
RIM_FADE = ((0.00, 150), (0.30, 95), (0.70, 30), (1.00, 0))

OUTER_RIM_W = 0.0045
OUTER_RIM_COLOR = (207, 209, 214)
OUTER_RIM_FADE = ((0.00, 255), (0.12, 190), (0.45, 60), (0.85, 0), (1.00, 0))

BORDER_COLOR = (32, 32, 32)
GLYPH_COLOR = (26, 26, 26)

SS = 3  # panel supersampling (pygame draws no AA edges)
GLYPH_SS = 4  # vector glyph supersampling

# Font candidates, best first. The first entry is this repo's bundled D-DIN
# Exp Bold -- the face the real 296 skin uses (skin_1280x720_car3588.py) -- and
# is tried as a file path; the rest go through pygame.font.match_font.
_BUNDLED_FONT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "src",
    "instrument_cluster",
    "assets",
    "fonts",
    "d-din",
    "D-DINExp-Bold.ttf",
)
FONT_CANDIDATES = (
    "Eurostile",
    "Bank Gothic",
    "Square721 BT",
    "DIN Condensed",
    "D-DIN Exp",
    "Arial Black",
    "Helvetica Neue Condensed Black",
    "Impact",
)


# --- small surface helpers --------------------------------------------------


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_rgb(a, b, t):
    return tuple(int(round(_lerp(a[i], b[i], t))) for i in range(3))


def _ramp(length: int, stops) -> list[tuple[int, int, int]]:
    """Sample a piecewise-linear colour ramp into `length` RGB triples.

    Stops are (position, colour) with position in 0..1 and colour either an RGB
    tuple or a plain grey level, which is all any of these ramps actually need.
    """
    pts = sorted((float(t), c if isinstance(c, tuple) else (c, c, c)) for t, c in stops)
    out = []
    for i in range(length):
        t = i / max(1, length - 1)
        if t <= pts[0][0]:
            out.append(pts[0][1])
            continue
        if t >= pts[-1][0]:
            out.append(pts[-1][1])
            continue
        for (t0, c0), (t1, c1) in zip(pts, pts[1:]):
            if t0 <= t <= t1:
                k = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                out.append(_lerp_rgb(c0, c1, k))
                break
    return out


def _ramp_surface(
    size: tuple[int, int], stops, vertical: bool = True
) -> pygame.Surface:
    """A ramp stretched across `size`. Built one pixel per step, then scaled on
    the flat axis only, so nothing is resampled along the gradient itself."""
    w, h = size
    n = max(1, h if vertical else w)
    strip = pygame.Surface((1, n) if vertical else (n, 1), pygame.SRCALPHA)
    for i, c in enumerate(_ramp(n, stops)):
        strip.set_at((0, i) if vertical else (i, 0), (c[0], c[1], c[2], 255))
    return pygame.transform.scale(strip, size)


def _alpha_ramp_surface(size, stops, vertical: bool = True) -> pygame.Surface:
    """Same idea, but the ramp drives alpha on a white surface -- a mask to
    multiply into another mask."""
    w, h = size
    n = max(1, h if vertical else w)
    strip = pygame.Surface((1, n) if vertical else (n, 1), pygame.SRCALPHA)
    for i, c in enumerate(_ramp(n, stops)):
        strip.set_at((0, i) if vertical else (i, 0), (255, 255, 255, c[0]))
    return pygame.transform.scale(strip, size)


def _mirrored_ramp_row(w: int, stops) -> pygame.Surface:
    """A 1px-tall row whose ramp runs in from *both* side edges.

    Sampled across the full width, then indexed by distance to the nearer edge,
    so a stop written at 0.045 means 4.5% of the panel width in from whichever
    side is closer -- and the two walls stay symmetric at any panel size.
    """
    vals = _ramp(w, stops)
    row = pygame.Surface((w, 1), pygame.SRCALPHA)
    for x in range(w):
        c = vals[min(x, w - 1 - x)]
        row.set_at((x, 0), (c[0], c[1], c[2], 255))
    return row


def _face(size: tuple[int, int]) -> pygame.Surface:
    """The lit face: the vertical roof ramp, multiplied by the side walls.

    Keeping the two axes separable and multiplying them is what gets the corners
    right for free -- a pixel in the top-left is shaded by the roof *and* by the
    wall, so it sits darker than either edge alone, which is exactly how the
    corners read in the reference. Drawing the rim as four mitred facets instead
    would put a hard seam on the diagonal that the photo does not have.
    """
    w, h = size
    surf = pygame.Surface(size, pygame.SRCALPHA)
    surf.blit(_ramp_surface(size, FACE_V_STOPS, vertical=True), (0, 0))
    surf.blit(
        pygame.transform.scale(_mirrored_ramp_row(w, FACE_H_STOPS), size),
        (0, 0),
        special_flags=pygame.BLEND_RGB_MULT,
    )
    return surf


def _rounded_mask(size: tuple[int, int], radius: int) -> pygame.Surface:
    mask = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    return mask


def _rim(size, radius: int, inset: int, width: int, color, fade) -> pygame.Surface:
    """A stroke on a rounded rect whose opacity falls off down the panel."""
    w, h = size
    surf = pygame.Surface(size, pygame.SRCALPHA)
    rect = pygame.Rect(inset, inset, w - 2 * inset, h - 2 * inset)
    if rect.width <= 0 or rect.height <= 0:
        return surf
    pygame.draw.rect(
        surf,
        (color[0], color[1], color[2], 255),
        rect,
        width=max(1, width),
        border_radius=max(0, radius - inset),
    )
    surf.blit(
        _alpha_ramp_surface(size, fade, True),
        (0, 0),
        special_flags=pygame.BLEND_RGBA_MULT,
    )
    return surf


def _blur(surf: pygame.Surface, radius: float) -> pygame.Surface:
    """Cheap gaussian-ish blur: downsample, bounce, upsample.

    pygame (non-ce) has no blur, and a real convolution over the shadow mask is
    far more than this needs -- two down/up round trips already read as soft at
    the ~9px radius the default size asks for.
    """
    if radius < 1:
        return surf
    w, h = surf.get_size()
    step = max(1, int(radius))
    sw, sh = max(1, w // step), max(1, h // step)
    small = pygame.transform.smoothscale(surf, (sw, sh))
    for _ in range(2):
        small = pygame.transform.smoothscale(small, (max(1, sw // 2), max(1, sh // 2)))
        small = pygame.transform.smoothscale(small, (sw, sh))
    return pygame.transform.smoothscale(small, (w, h))


# --- font resolution --------------------------------------------------------


def resolve_font(font_path: str | None, verbose: bool = True) -> tuple[str | None, str]:
    """Return (path, human name). path None means pygame's built-in default."""
    if font_path:
        if os.path.isfile(font_path):
            return font_path, os.path.basename(font_path)
        print(
            f"[gear] font_path {font_path!r} not found, falling back", file=sys.stderr
        )

    bundled = os.path.normpath(_BUNDLED_FONT)
    if os.path.isfile(bundled):
        return bundled, os.path.basename(bundled)

    for name in FONT_CANDIDATES:
        found = pygame.font.match_font(name, bold=True)
        if found:
            return found, f"{name} ({os.path.basename(found)})"
    return None, "pygame default (no candidate matched)"


class FerrariGearPanel:
    """The gear panel. Renders once per value change, then blits.

    `image` is the full surface *including* the drop shadow margin; `panel_rect`
    locates the panel body inside it. `draw()` handles that offset, so callers
    can position by the panel's own centre and ignore the shadow.
    """

    def __init__(
        self,
        width: int = 310,
        height: int | None = None,
        font_path: str | None = None,
        vector_glyph: str | bool = "auto",
        verbose: bool = True,
    ):
        if not pygame.font.get_init():
            pygame.font.init()

        self.w = int(width)
        self.h = int(height) if height else int(round(width / ASPECT))
        self.radius = max(1, int(round(RADIUS_W * self.w)))
        self.border_width = max(2, int(round(BORDER_W * self.w)))
        self.shadow_blur = SHADOW_BLUR_W * self.w
        self.shadow_offset = int(round(SHADOW_OFF_H * self.h))
        self.pad = int(round(self.shadow_blur * 2.5)) + self.shadow_offset + 2

        self.font_path, self.font_name = resolve_font(font_path, verbose)
        self._is_default_font = self.font_path is None
        if verbose:
            print(f"[gear] glyph font: {self.font_name}")

        # vector_glyph: True forces it, False never uses it, "auto" uses it only
        # when the font search came up empty (the default face's "0" is an oval,
        # which is precisely the shape the reference is not).
        if vector_glyph == "auto":
            self.vector_glyph = self._is_default_font
        else:
            self.vector_glyph = bool(vector_glyph)
        if verbose and self.vector_glyph:
            print("[gear] vector glyph renderer active for '0'")

        self._font = self._fit_font()
        self._body = self._build_body()  # panel + shadow, no glyph
        self.image = self._body.copy()
        self.panel_rect = pygame.Rect(self.pad, self.pad, self.w, self.h)
        self.rect = self.image.get_rect()
        self._value_str: str | None = None
        self.dirty = True
        self.set_value("N")

    # -- geometry ----------------------------------------------------------

    def _fit_font(self) -> pygame.font.Font:
        """Size the font so the *ink* of '0' is CAP_HEIGHT_H of the panel.

        Point size is not cap height and the ratio differs per face, so measure
        it: render a probe, take the bounding rect, scale. '0' is the metric
        char for every value, so "1" and "0" share a cap height instead of each
        being fitted to its own ink.
        """
        target = CAP_HEIGHT_H * self.h
        probe_size = 200

        def make(size: int) -> pygame.font.Font:
            if self.font_path:
                return pygame.font.Font(self.font_path, size)
            return pygame.font.Font(None, size)

        probe = make(probe_size)
        ink = probe.render("0", True, GLYPH_COLOR).get_bounding_rect().height
        if ink <= 0:
            return probe
        size = max(8, int(round(probe_size * target / ink)))
        return make(size)

    def _build_body(self) -> pygame.Surface:
        """Shadow, gradient body, rounded clip, border, mitred bevel.

        Built at SS x and downsampled: pygame.draw's rounded rects and polygons
        are hard aliased, and at the 20px radius here that stair-steps visibly
        on a near-white panel -- as would the miter diagonals.
        """
        w, h, r = self.w * SS, self.h * SS, self.radius * SS
        pad = self.pad

        out = pygame.Surface((self.w + 2 * pad, self.h + 2 * pad), pygame.SRCALPHA)

        # 1. drop shadow: a blurred rounded-rect alpha mask behind everything.
        shadow = pygame.Surface(out.get_size(), pygame.SRCALPHA)
        pygame.draw.rect(
            shadow,
            (0, 0, 0, int(round(255 * SHADOW_ALPHA))),
            pygame.Rect(pad, pad + self.shadow_offset, self.w, self.h),
            border_radius=self.radius,
        )
        out.blit(_blur(shadow, self.shadow_blur), (0, 0))

        # 2. the lit face, clipped to the rounded rect.
        panel = pygame.Surface((w, h), pygame.SRCALPHA)
        panel.blit(_face((w, h)), (0, 0))
        panel.blit(
            _rounded_mask((w, h), r), (0, 0), special_flags=pygame.BLEND_RGBA_MULT
        )

        # 3. outer stroke, on the same rounded rect.
        bw = self.border_width * SS
        pygame.draw.rect(
            panel, BORDER_COLOR, pygame.Rect(0, 0, w, h), width=bw, border_radius=r
        )

        # 4. the two rim lines, over the stroke rather than under it -- drawing
        #    them first would just hand the outer few pixels back to step 3.
        panel.blit(
            _rim((w, h), r, bw, max(SS, int(round(RIM_W * w))), RIM_COLOR, RIM_FADE),
            (0, 0),
        )
        panel.blit(
            _rim(
                (w, h),
                r,
                0,
                max(SS, int(round(OUTER_RIM_W * w))),
                OUTER_RIM_COLOR,
                OUTER_RIM_FADE,
            ),
            (0, 0),
        )

        out.blit(pygame.transform.smoothscale(panel, (self.w, self.h)), (pad, pad))
        return out

    # -- glyph -------------------------------------------------------------

    def _vector_zero(self) -> pygame.Surface:
        """'0' as a stroked rounded-rect ring, supersampled then downscaled."""
        s = GLYPH_SS
        ow = int(round(VEC_W * self.w)) * s
        oh = int(round(VEC_H * self.h)) * s
        stroke = max(1, int(round(VEC_STROKE_W * self.w)) * s)
        rad = int(round(VEC_RADIUS_W * self.w)) * s

        surf = pygame.Surface((ow, oh), pygame.SRCALPHA)
        pygame.draw.rect(
            surf, GLYPH_COLOR, pygame.Rect(0, 0, ow, oh), border_radius=rad
        )
        inner = pygame.Rect(stroke, stroke, ow - 2 * stroke, oh - 2 * stroke)
        if inner.width > 0 and inner.height > 0:
            # Drawing straight RGBA punches the counter out: draw.rect writes
            # the alpha channel, so (0,0,0,0) erases rather than blending.
            pygame.draw.rect(
                surf, (0, 0, 0, 0), inner, border_radius=max(0, rad - stroke)
            )
        return pygame.transform.smoothscale(surf, (ow // s, oh // s))

    def _render_glyph(self, text: str) -> pygame.Surface:
        if self.vector_glyph and text == "0":
            return self._vector_zero()
        return self._font.render(text, True, GLYPH_COLOR)

    # -- public API --------------------------------------------------------

    def set_value(self, value) -> None:
        """Accepts a gear int (0 = R, -1 = N, -2 = P) or a literal string."""
        if isinstance(value, str):
            text = value
        elif value == 0:
            text = "R"
        elif value == -1:
            text = "N"
        elif value == -2:
            text = "P"
        else:
            text = str(value)

        if text == self._value_str:
            return
        self._value_str = text

        self.image = self._body.copy()
        glyph = self._render_glyph(text)
        ink = glyph.get_bounding_rect()
        if ink.width == 0 or ink.height == 0:
            self.dirty = True
            return
        # Centre the *ink*, not the surface -- font surfaces carry ascender and
        # descender padding that would drop the digit low in the panel.
        cx = self.pad + self.w / 2.0
        cy = self.pad + self.h / 2.0 - OPTICAL_RISE_H * self.h
        x = int(round(cx - ink.centerx))
        y = int(round(cy - ink.centery))
        self.image.blit(glyph, (x, y))
        self.dirty = True

    @property
    def value(self) -> str | None:
        return self._value_str

    def set_vector_glyph(self, enabled: bool) -> None:
        if bool(enabled) == self.vector_glyph:
            return
        self.vector_glyph = bool(enabled)
        text, self._value_str = self._value_str, None
        self.set_value(text)

    def draw(self, target: pygame.Surface, center=None, topleft=None) -> pygame.Rect:
        """Blit the panel; `center`/`topleft` refer to the panel, not the shadow."""
        if center is not None:
            pos = (
                int(center[0] - self.w / 2 - self.pad),
                int(center[1] - self.h / 2 - self.pad),
            )
        elif topleft is not None:
            pos = (int(topleft[0] - self.pad), int(topleft[1] - self.pad))
        else:
            pos = (0, 0)
        self.rect = self.image.get_rect(topleft=pos)
        self.dirty = False
        return target.blit(self.image, pos)


# --- demo -------------------------------------------------------------------


def _demo(args: argparse.Namespace) -> int:
    if args.shot:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()

    size = (args.width * 2 + 120, int(args.width / ASPECT) + 200)
    screen = pygame.display.set_mode(size)
    pygame.display.set_caption("296 GT3 gear panel")

    vector = True if args.vector else "auto"
    panel = FerrariGearPanel(args.width, font_path=args.font, vector_glyph=vector)
    panel.set_value(args.value)

    hint_font = pygame.font.Font(None, 22)
    gears = [-2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8]
    idx = gears.index(args.value) if args.value in gears else 4

    def paint():
        screen.fill((18, 18, 20))
        panel.draw(screen, center=(size[0] // 2, size[1] // 2 - 20))
        hint = "UP/DOWN or 0-9  N R P  |  V vector: %s  |  S save  |  ESC" % (
            "on" if panel.vector_glyph else "off"
        )
        surf = hint_font.render(hint, True, (150, 150, 155))
        screen.blit(surf, surf.get_rect(midbottom=(size[0] // 2, size[1] - 18)))
        pygame.display.flip()

    paint()
    if args.shot:
        pygame.image.save(screen, args.shot)
        print(f"[gear] wrote {args.shot}")
        pygame.quit()
        return 0

    clock = pygame.time.Clock()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key == pygame.K_UP:
                    idx = min(idx + 1, len(gears) - 1)
                    panel.set_value(gears[idx])
                elif event.key == pygame.K_DOWN:
                    idx = max(idx - 1, 0)
                    panel.set_value(gears[idx])
                elif event.key == pygame.K_v:
                    panel.set_vector_glyph(not panel.vector_glyph)
                elif event.key == pygame.K_n:
                    panel.set_value("N")
                elif event.key == pygame.K_r:
                    panel.set_value("R")
                elif event.key == pygame.K_p:
                    panel.set_value("P")
                elif event.key == pygame.K_s:
                    pygame.image.save(screen, "gear_panel.png")
                    print("[gear] wrote gear_panel.png")
                elif pygame.K_0 <= event.key <= pygame.K_9:
                    panel.set_value(str(event.key - pygame.K_0))
        paint()
        clock.tick(60)

    pygame.quit()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--width", type=int, default=310, help="panel width in px")
    ap.add_argument("--font", default=None, help="explicit .ttf/.otf path")
    ap.add_argument("--vector", action="store_true", help="force the vector '0'")
    ap.add_argument("--value", default="3", help='initial gear: "1".."8", N, R, P')
    ap.add_argument("--shot", default=None, help="render one frame to PNG and exit")
    # --value stays a literal string so "0" is the digit zero, not the int 0
    # (which set_value maps to R, GT7 style). Use "N"/"R"/"P" for those.
    return _demo(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
