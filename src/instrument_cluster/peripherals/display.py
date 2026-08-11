"""Display profiles and the render/input bridge between the *logical*
render surface and the *physical* panel the cluster runs on.

Every supported panel renders at its **native** resolution: the HMI's
geometry comes from a per-resolution skin (``ui/skins/``) matching the
profile's ``logical_size``, so nothing is stretched at present time. Each
panel is described by a :class:`DisplayProfile` that knows how to:

* create the on-screen surface (GPU vs. software),
* present the logical surface onto the physical panel (rotation only —
  no resampling on any shipped profile),
* map raw input events back into logical coordinates.

Supported panels:

* **Raspberry Pi Display 2** – 720 x 1280 portrait panel mounted in
  landscape. Logical 1280 x 720, rotated 270 deg onto the panel by the GPU
  renderer (1:1 pixels, no resampling).
* **Waveshare 7" DSI** – 1024 x 600 landscape panel, rendered natively.
* **Waveshare 5" DSI** – 800 x 480 landscape panel, rendered natively.
* **Dev** – a resizable desktop window (also the PC app). The window opens
  at 1280 x 720 and pygame's SCALED mode stretches the logical surface to
  whatever size the user drags it to (aspect preserved, input mapped back
  automatically). Set ``display`` in the config to a panel profile name to
  preview that panel's skin in a native-sized window.

``DESIGN_WIDTH``/``DESIGN_HEIGHT`` (1280 x 720) survive as the
**custom-dashboard spec space**: user layouts are authored against it on
every panel (see ``ui/widgets/registry.py``), and ``scale_factors()`` /
``scale_uniform()`` map it to the active logical size. Skinned code never
uses them.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from ..logger import Logger

logger = Logger("display").get()

# The design (authoring) resolution. All widget coordinates and font sizes are
# authored against this reference; the scaling helpers in ui/utils.py map them
# to the active profile's logical_size so each panel renders natively.
DESIGN_WIDTH = 1280
DESIGN_HEIGHT = 720
DESIGN_SIZE = (DESIGN_WIDTH, DESIGN_HEIGHT)

# Back-compat aliases (the dev/Pi panels render at the design resolution).
LOGICAL_WIDTH = DESIGN_WIDTH
LOGICAL_HEIGHT = DESIGN_HEIGHT
LOGICAL_SIZE = DESIGN_SIZE

# Profile identifiers (also accepted in config.json's "display" field).
RPI_DISPLAY_2 = "rpi_display_2"
WAVESHARE_7 = "waveshare_7"
WAVESHARE_5 = "waveshare_5"
DEV = "dev"

_FINGER_EVENTS = (pygame.FINGERDOWN, pygame.FINGERUP, pygame.FINGERMOTION)
_MOUSE_EVENTS = (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION)


@dataclass(frozen=True)
class DisplayProfile:
    """Static description of a physical panel and how to drive it."""

    name: str
    physical_size: tuple[int, int]
    rotation: int = 0  # degrees the logical surface is rotated for presentation
    renderer: str = "software"  # "gpu" | "software"
    logical_size: tuple[int, int] = LOGICAL_SIZE
    # Desktop windows only: let the user resize the window, with pygame's
    # SCALED mode stretching the logical surface to fit.
    resizable: bool = False

    @property
    def logical_width(self) -> int:
        return self.logical_size[0]

    @property
    def logical_height(self) -> int:
        return self.logical_size[1]

    @property
    def uses_hardware_renderer(self) -> bool:
        return self.renderer == "gpu"

    def to_logical(self, event: pygame.event.Event) -> tuple[int, int] | None:
        """Map a mouse/touch event into logical (1280x720) coordinates.

        Touch events arrive normalized to ``[0, 1]`` over the physical panel;
        mouse events arrive in physical pixels. Both are reduced to a normalized
        point and then mapped into the logical space, accounting for panel
        rotation.
        """
        if event.type in _FINGER_EVENTS:
            nx, ny = float(event.x), float(event.y)
        elif event.type in _MOUSE_EVENTS:
            surf = pygame.display.get_surface()
            if surf is None:
                return None
            pw, ph = surf.get_size()
            if pw == 0 or ph == 0:
                return None
            px, py = event.pos
            nx, ny = px / pw, py / ph
        else:
            return None

        lw, lh = self.logical_size
        if self.rotation == 270:
            # Portrait panel mounted in landscape: the panel's x-axis runs along
            # the logical y-axis and is inverted relative to the logical x-axis.
            x = (1.0 - nx) * lw
            y = ny * lh
        else:
            x = nx * lw
            y = ny * lh

        return int(x), int(y)


# Registry of known profiles by name.
_PROFILES = {
    RPI_DISPLAY_2: DisplayProfile(
        name=RPI_DISPLAY_2,
        physical_size=(720, 1280),
        rotation=270,
        renderer="gpu",
    ),
    WAVESHARE_7: DisplayProfile(
        name=WAVESHARE_7,
        physical_size=(1024, 600),
        # Native landscape panel: render directly at panel resolution (the UI
        # scales the 1280x720 design down to this), so no post-scale blur.
        logical_size=(1024, 600),
        rotation=0,
        renderer="software",
    ),
    WAVESHARE_5: DisplayProfile(
        name=WAVESHARE_5,
        physical_size=(800, 480),
        # Native landscape panel, rendered at panel resolution like the 7".
        logical_size=(800, 480),
        rotation=0,
        renderer="software",
    ),
    DEV: DisplayProfile(
        name=DEV,
        physical_size=LOGICAL_SIZE,
        rotation=0,
        renderer="software",
        resizable=True,
    ),
}


class _DisplayState:
    """Mutable holder for the process-wide active display selection.

    The getters below read attributes on this single instance; :class:`Display`
    writes them when it is created/closed. Storing them on one instance (rather
    than module-level names) means the writers don't need ``global``.

    * ``profile`` – the profile selected for this process. Lazily defaults to
      DEV so that code paths exercised before a Display exists (e.g. tests
      constructing widgets) still work.
    * ``display`` – the active Display instance, set while the app is running
      and cleared on teardown; None otherwise.
    """

    def __init__(self) -> None:
        self.profile: DisplayProfile | None = None
        self.display: Display | None = None


_state = _DisplayState()


def active_profile() -> DisplayProfile:
    """Return the active display profile, defaulting to the dev profile."""
    if _state.profile is None:
        _state.profile = _PROFILES[DEV]
    return _state.profile


def scale_factors() -> tuple[float, float]:
    """(x, y) factors mapping design coordinates to the active logical size."""
    lw, lh = active_profile().logical_size
    return lw / DESIGN_WIDTH, lh / DESIGN_HEIGHT


def scale_uniform() -> float:
    """Single factor for fonts/icons/radii (min of x and y to avoid overflow)."""
    sx, sy = scale_factors()
    return min(sx, sy)


def active_display() -> Display | None:
    """Return the active Display, or None if the app isn't running."""
    return _state.display


def _read_pi_model() -> str:
    try:
        with open("/proc/device-tree/model", "r") as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return ""


def is_raspberry_pi() -> bool:
    return "Raspberry Pi" in _read_pi_model()


def is_raspberry_pi_display_2() -> bool:
    """True when the active panel is the Raspberry Pi Display 2."""
    return active_profile().name == RPI_DISPLAY_2


def _detect_physical_size() -> tuple[int, int] | None:
    """Best-effort native panel resolution (requires pygame to be initialized)."""
    try:
        info = pygame.display.Info()
    except pygame.error:
        return None
    w, h = info.current_w, info.current_h
    if w <= 0 or h <= 0:
        return None
    return (w, h)


def _match_by_resolution(size: tuple[int, int]) -> DisplayProfile | None:
    for profile in (
        _PROFILES[RPI_DISPLAY_2],
        _PROFILES[WAVESHARE_7],
        _PROFILES[WAVESHARE_5],
    ):
        if profile.physical_size == size:
            return profile
    return None


def _resolve_profile(configured: str | None = None) -> DisplayProfile:
    """Resolve which display profile to use.

    Resolution order:

    1. An explicit, known ``configured`` name always wins (config override).
    2. On a Raspberry Pi, auto-detect by the panel's native resolution,
       falling back to the Pi Display 2 if the resolution is unrecognized.
    3. Otherwise use the dev (windowed) profile.
    """
    if configured and configured not in ("", "auto"):
        profile = _PROFILES.get(configured)
        if profile is not None:
            return profile
        logger.warning(f"Unknown display '{configured}', falling back to auto-detect.")

    if is_raspberry_pi():
        size = _detect_physical_size()
        if size is not None:
            matched = _match_by_resolution(size)
            if matched is not None:
                return matched
            logger.warning(
                f"Unrecognized panel resolution {size}; defaulting to {RPI_DISPLAY_2}."
            )
        return _PROFILES[RPI_DISPLAY_2]

    return _PROFILES[DEV]


class Display:
    """Owns the on-screen surface and presents the logical surface to it.

    Constructing a Display resolves the physical panel to drive (from the
    optional ``configured`` profile name, otherwise auto-detected) and
    registers it as the process-wide active display, so input mapping can
    translate physical input into logical coordinates and ``active_skin()``
    resolves the matching per-resolution skin. Call :meth:`close` on
    teardown to clear that registration.

    Callers render every frame into :attr:`surface` (at the profile's
    native logical size) and then call :meth:`present` to push it to the
    panel.
    """

    def __init__(self, configured: str | None = None):
        profile = _resolve_profile(configured)
        self.profile = profile
        self._gpu_renderer = None
        self._scaled: pygame.Surface | None = None

        if profile.uses_hardware_renderer:
            # GPU path: render into an off-screen logical surface; the renderer
            # rotates/scales it onto the physical panel.
            from ..core.system.hardware_renderer import HardwareRenderer

            self._gpu_renderer = HardwareRenderer(
                physical_size=profile.physical_size,
                logical_size=profile.logical_size,
                rotation_angle=profile.rotation,
            )
            self.surface = pygame.Surface(profile.logical_size)
        elif profile.physical_size == profile.logical_size:
            # Software path, no scaling: the window *is* the logical surface.
            if profile.resizable:
                self.surface = self._resizable_window(profile)
            else:
                self.surface = pygame.display.set_mode(profile.physical_size)
        else:
            # Software path with scaling: render off-screen, scale on present.
            self._screen = pygame.display.set_mode(profile.physical_size)
            self.surface = pygame.Surface(profile.logical_size)

        # Publish ourselves (and our profile) as the process-wide active display.
        _state.profile = profile
        _state.display = self
        logger.info(
            f"Active display: {profile.name} "
            f"physical={profile.physical_size} rotation={profile.rotation} "
            f"renderer={profile.renderer}"
        )

    @staticmethod
    def _resizable_window(profile: DisplayProfile) -> pygame.Surface:
        """Open a resizable desktop window at the logical resolution.

        SCALED keeps the returned surface at the logical size while pygame
        stretches it to the actual window (aspect preserved) and maps mouse
        input back into logical coordinates — so callers never see the
        window size. vsync paces the otherwise-uncapped main loop; both are
        best-effort because some drivers (e.g. the dummy driver in tests)
        support neither.
        """
        flags = pygame.SCALED | pygame.RESIZABLE
        try:
            return pygame.display.set_mode(profile.physical_size, flags, vsync=1)
        except pygame.error:
            pass
        try:
            return pygame.display.set_mode(profile.physical_size, flags)
        except pygame.error:
            logger.warning("Resizable window unavailable; using a fixed window.")
            return pygame.display.set_mode(profile.physical_size)

    def close(self) -> None:
        """Clear this display's process-wide registration (call on teardown)."""
        if _state.display is self:
            _state.display = None

    @property
    def scales(self) -> bool:
        """True when present() must scale (logical != physical, software)."""
        return (
            self._gpu_renderer is None
            and self.profile.physical_size != self.profile.logical_size
        )

    def present(self, dirty_rects) -> None:
        """Push the current logical surface to the panel."""
        if not dirty_rects:
            return

        if self._gpu_renderer is not None:
            self._gpu_renderer.render(self.surface)
        elif self.scales:
            screen = pygame.display.get_surface()
            pygame.transform.scale(self.surface, self.profile.physical_size, screen)
            pygame.display.flip()
        else:
            # Logical surface is the display surface; flush dirty rects only.
            pygame.display.update(dirty_rects)

    def present_full(self) -> None:
        """Force-present the entire logical surface (e.g. before a reboot)."""
        self.present([self.surface.get_rect()])
