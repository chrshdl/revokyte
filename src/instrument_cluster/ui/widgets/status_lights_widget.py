import pygame
from pygame.sprite import DirtySprite

from ...core.vehicle.vehicle_bus import VehicleBus
from ..colors import Color
from ..skins import active_skin


class StatusLightsWidget(DirtySprite):
    """Bezel LED column at the screen edge.

    Three dots stacked vertically. The middle dot lights
    amber while traction control cuts power (flags.tcs_active),
    the outer pair lights blue while stability management
    intervenes (flags.asm_active). Interventions can last a
    single frame, so each light holds for a short minimum time
    to stay visible.
    """

    _HOLD_S = 0.12

    def __init__(self, rect: tuple[int, int, int, int]):
        super().__init__()
        x, y, w, h = rect
        self.image = pygame.Surface((w, h), pygame.SRCALPHA).convert_alpha()
        self.rect = self.image.get_rect(topleft=(x, y))

        # The column stays centered in the strip rect; the skin must keep
        # spacing + radius within half the rect height or the outer dots
        # clip.
        skin = active_skin().dashboard
        self._radius = skin.status_light_dot_radius
        step = skin.status_light_dot_spacing
        self._centers = [(w // 2, h // 2 + dy) for dy in (-step, 0, step)]

        # LED sprites are pre-rendered once; pygame has no radial gradient
        # primitive, so they're built from concentric circles.
        self._dot_unlit = self._make_dot(None)
        self._dot_tc = self._make_dot(Color[skin.status_light_tc_color].rgb())
        self._dot_asm = self._make_dot(Color[skin.status_light_asm_color].rgb())

        self._tc_hold = 0.0
        self._asm_hold = 0.0
        self._last_state: tuple[bool, bool] | None = None

        self.visible = 1
        self.set_value((False, False))

    @staticmethod
    def _lerp(a, b, t: float) -> tuple[int, int, int]:
        return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))

    def _make_dot(self, color: tuple[int, int, int] | None) -> pygame.Surface:
        """Pre-render one LED as a bezel-mounted lens.

        Modeled on the round status LEDs recessed in a GT3 dashboard's
        bezel: a matte plastic housing ring seats a domed lens. Lit:
        whitened hot core -> saturated body -> darker rim, separated from
        the housing by a dark seam groove, wrapped in a soft bloom that
        bleeds past the bezel edge. Unlit: a dark lens in the same housing.
        Both carry a small specular glint, offset off-center, simulating
        the dome catching ambient light — without it a flat-lit circle
        reads as a painted disc rather than glass/plastic. Drawn 4x
        oversized and smooth-scaled down, since concentric pygame circles
        alias badly at LED size.
        """
        ss = 4
        r = self._radius * ss
        bezel_r = r + round(3 * ss)
        halo_r = round(bezel_r * 1.6) if color is not None else bezel_r + ss
        size = halo_r * 2
        surf = pygame.Surface((size, size), pygame.SRCALPHA).convert_alpha()
        center = (halo_r, halo_r)

        if color is not None:
            # bloom: soft alpha ramp bleeding out past the bezel edge
            for i in range(halo_r, bezel_r, -1):
                t = (halo_r - i) / (halo_r - bezel_r)
                pygame.draw.circle(surf, (*color, round(80 * t * t)), center, i)

        # bezel: matte plastic housing ring, faintly tinted by the LED
        # color when lit (light leaking into the mount), neutral when unlit
        bezel_outer = Color.DARKEST_GREY.rgb()
        bezel_inner = (
            self._lerp(Color.DARKEST_GREY.rgb(), color, 0.2)
            if color is not None
            else Color.DARK_GREY.rgb()
        )
        for i in range(bezel_r, r, -1):
            t = (i - r) / (bezel_r - r)
            pygame.draw.circle(surf, self._lerp(bezel_inner, bezel_outer, t), center, i)
        # machined lip: a thin lighter ring at the outer edge of the bezel
        pygame.draw.circle(surf, Color.MID_GREY.rgb(), center, bezel_r, ss)
        # seam: a dark groove where the lens meets the housing
        pygame.draw.circle(surf, Color.BLACK.rgb(), center, r, round(1.5 * ss))

        # lens body
        if color is None:
            edge = Color.DARKEST_GREY.rgb()
            core = Color.GREY.rgb()
            for i in range(r, 0, -1):
                t = i / r  # 1 at the rim, 0 at the center
                pygame.draw.circle(surf, self._lerp(core, edge, t), center, i)
        else:
            # body: darker rim -> whitened core
            rim = self._lerp(color, Color.BLACK.rgb(), 0.35)
            core = self._lerp(color, Color.WHITE.rgb(), 0.5)
            for i in range(r, 0, -1):
                t = i / r
                pygame.draw.circle(surf, self._lerp(core, rim, t), center, i)

        # specular glint: the domed lens catching ambient light. A single
        # soft circular blob reads as just another gradient ring, so this
        # pairs a broad, elongated, rotated sheen (the curved surface
        # catching light from one side) with a small hard pinpoint (the
        # actual catch-light) — the combination is what sells "glass/
        # plastic" instead of "painted disc".
        strength = 1.0 if color is not None else 0.4

        sheen_w, sheen_h = round(r * 0.65), round(r * 0.3)
        sheen = pygame.Surface((sheen_w * 2, sheen_h * 2), pygame.SRCALPHA)
        steps = max(sheen_w, sheen_h)
        for i in range(steps, 0, -1):
            t = i / steps
            alpha = round(140 * strength * (1 - t) ** 3)
            if alpha <= 0:
                continue
            rect = pygame.Rect(0, 0, max(2, round(sheen_w * 2 * t)), max(2, round(sheen_h * 2 * t)))
            rect.center = (sheen_w, sheen_h)
            pygame.draw.ellipse(sheen, (255, 255, 255, alpha), rect)
        sheen = pygame.transform.rotate(sheen, 35)
        sw, sh = sheen.get_size()
        surf.blit(
            sheen,
            (center[0] - round(r * 0.4) - sw // 2, center[1] - round(r * 0.42) - sh // 2),
        )

        pin_center = (center[0] - round(r * 0.34), center[1] - round(r * 0.4))
        pin_r = max(1, round(r * 0.1))
        for i in range(pin_r, 0, -1):
            t = i / pin_r
            pygame.draw.circle(
                surf, (255, 255, 255, round(210 * strength * (1 - t * t))), pin_center, i
            )

        return pygame.transform.smoothscale(surf, (size // ss, size // ss))

    def set_value(self, state: tuple[bool, bool]):
        """Redraw the LED column for ``(tc_lit, asm_lit)``."""
        if state == self._last_state:
            return
        self._last_state = state
        tc_lit, asm_lit = state

        asm_dot = self._dot_asm if asm_lit else self._dot_unlit
        tc_dot = self._dot_tc if tc_lit else self._dot_unlit

        self.image.fill((0, 0, 0, 0))
        for (cx, cy), dot in zip(self._centers, (asm_dot, tc_dot, asm_dot)):
            self.image.blit(
                dot, (cx - dot.get_width() // 2, cy - dot.get_height() // 2)
            )
        self.dirty = 1

    def update(self, bus: VehicleBus, dt: float):
        frame = bus.frame
        if frame is None:
            return

        flags = getattr(frame, "flags", None)
        tc_active = bool(flags and flags.tcs_active)
        asm_active = bool(flags and flags.asm_active)

        self._tc_hold = self._HOLD_S if tc_active else max(0.0, self._tc_hold - dt)
        self._asm_hold = self._HOLD_S if asm_active else max(0.0, self._asm_hold - dt)

        self.set_value((self._tc_hold > 0.0, self._asm_hold > 0.0))
