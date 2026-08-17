from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Literal

import pygame
from pygame.sprite import DirtySprite

from ...colors import Color
from ...utils import FontFamily, load_font
from .container import Container


class ButtonState(Enum):
    IDLE = auto()
    PRESSED = auto()
    RELEASED = auto()
    LONGPRESSED = auto()


@dataclass(frozen=True)
class ButtonEvents:
    """Pygame event types to post for button interactions."""

    pressed: int
    released: int
    long_pressed: int | None = None
    selected: int | None = None


class AbstractButton(DirtySprite):
    """Base class for buttons with unified mouse/touch handling."""

    LONG_PRESS_SECONDS = 2.0

    def __init__(
        self,
        rect,
        events: ButtonEvents,
        event_data: dict | None = None,
        enabled: bool = True,
    ):
        super().__init__()
        self.rect = pygame.Rect(rect)
        self.events = events
        self.event_data = event_data or {}
        self.state = ButtonState.IDLE
        self._enabled = enabled

        # Which pointer currently owns the press:
        # - None: no active press
        # - 0: mouse
        # - finger_id (int): touch finger id
        self._active_pointer: int | None = None

        self._pressed_time = 0.0
        self._long_fired = False
        self.auto_reset_released = True  # one-tick RELEASED state

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        if self._enabled != value:
            self._enabled = value
            # Force state to IDLE if disabling while pressed
            if not value:
                self.state = ButtonState.IDLE
                self._active_pointer = None
            self._on_visual_change()

    # ----- helpers -----------------------------------------------------

    def _on_visual_change(self) -> None:
        """Called when visual state may have changed."""

        self.dirty = 1

    def draw(self, surface: pygame.Surface) -> None:
        raise NotImplementedError("draw() must be overridden.")

    def is_pressed(self) -> bool:
        # Treat LONGPRESSED as pressed for visuals.
        return self.state in (ButtonState.PRESSED, ButtonState.LONGPRESSED)

    def is_released(self) -> bool:
        return self.state == ButtonState.RELEASED

    @staticmethod
    def _screen_size() -> tuple[int, int]:
        surf = pygame.display.get_surface()
        return surf.get_size() if surf else (0, 0)

    @staticmethod
    def _event_xy(event) -> tuple[int, int] | None:
        """
        Universal input scaler. Maps any mouse/touch input into the app's
        logical (native panel) resolution using the active display profile,
        which accounts for the panel's physical size and rotation.
        """
        from ....peripherals.display import active_profile

        return active_profile().to_logical(event)

    @staticmethod
    def _pointer_id(event) -> int | None:
        """Map a pygame mouse/touch event to a pointer id."""

        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            return 0
        if event.type in (pygame.FINGERDOWN, pygame.FINGERUP):
            return getattr(event, "finger_id", None)
        # Motion is deliberately not mapped: a press holds its highlight
        # while the pointer is dragged off, and only the release decides
        # whether it counted. See test_button_drag.py.
        return None

    def is_inside_xy(self, x: int, y: int) -> bool:
        return self.rect.collidepoint(x, y)

    def is_inside(self, event) -> bool:
        xy = self._event_xy(event)
        return False if xy is None else self.is_inside_xy(*xy)

    # ----- input/state machine ----------------------------------------

    def handle_event(self, event) -> None:
        """Handle mouse/touch down/up events and post configured pygame events."""

        if not self._enabled:
            return

        pid = self._pointer_id(event)
        if pid is None:
            return

        xy = self._event_xy(event)
        if xy is None:
            return

        prev_state = self.state
        inside = self.is_inside_xy(*xy)

        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
            # Ignore secondary presses while another pointer owns this button.
            if self._active_pointer is not None and self._active_pointer != pid:
                return

            if inside:
                if not self.is_pressed():
                    pygame.event.post(
                        pygame.event.Event(self.events.pressed, self.event_data)
                    )
                self.state = ButtonState.PRESSED
                self._active_pointer = pid
                self._pressed_time = 0.0
                self._long_fired = False

        elif event.type in (pygame.MOUSEBUTTONUP, pygame.FINGERUP):
            if self._active_pointer != pid:
                return

            # Release always clears pointer ownership.
            self._active_pointer = None
            self._pressed_time = 0.0

            if inside:
                # Keep the original semantics: do not post *released* if a
                # long-press was already fired.
                if not self._long_fired:
                    pygame.event.post(
                        pygame.event.Event(self.events.released, self.event_data)
                    )
                self.state = ButtonState.RELEASED
            else:
                self.state = ButtonState.IDLE

            self._long_fired = False

        if self.state != prev_state:
            self._on_visual_change()

    def update(self, dt: float) -> None:
        """Update internal timers. `dt` is expected in seconds."""

        prev_state = self.state

        if self.state == ButtonState.PRESSED:
            self._pressed_time += float(dt)
            if (
                not self._long_fired
                and self.events.long_pressed is not None
                and self._pressed_time >= self.LONG_PRESS_SECONDS
            ):
                pygame.event.post(
                    pygame.event.Event(self.events.long_pressed, self.event_data)
                )
                self._long_fired = True
                self.state = ButtonState.LONGPRESSED
        else:
            self._pressed_time = 0.0

        # ButtonState.RELEASED lasts exactly one update tick.
        if self.state == ButtonState.RELEASED and self.auto_reset_released:
            self.state = ButtonState.IDLE

        if self.state != prev_state:
            self._on_visual_change()


class ButtonGroup(Container):
    """A positioned container that manages multiple buttons."""

    def __init__(
        self,
        buttons: list[AbstractButton] | None = None,
        position: tuple[int, int] | None = (0, 0),
        visible: bool = True,
    ):
        super().__init__(x=position[0], y=position[1], is_visible=visible)
        if buttons:
            self.add(*buttons)

    def add_button(self, button: AbstractButton) -> None:
        self.add(button)

    def extend_buttons(self, buttons: list[AbstractButton]) -> None:
        self.add(*buttons)


class Button(AbstractButton):
    """Lightweight button widgets for Pygame with text+icon layout.

    This module provides:

    * `AbstractButton`: input/state handling (mouse + touch), no visuals.
    * `ButtonGroup`: convenience container for multiple buttons.
    * `Button`: a concrete rectangular button that can render text and an optional
      icon with flexible positioning, spacing, padding, and alignment.

    Performance notes
    -----------------
    The implementation is designed to be cheap per-frame:

    * Text and icon surfaces are cached and only re-rendered when their inputs
      change (text, color, font, antialias, etc.).
    * Layout is cached and recomputed only when the button size, padding, content
      surfaces, or layout settings change.
    * A composed button surface (background + border + content) is cached and only
      rebuilt when something that affects visuals changes.
    """

    def __init__(
        self,
        rect,
        text: str,
        events: ButtonEvents | None = None,
        event_data: dict | None = None,
        show_border: bool = True,
        font: pygame.font.Font | None = None,
        text_color: tuple[int, int, int] | None = None,
        antialias: bool | None = None,
        enabled: bool = True,
        *,
        icon: str | None = None,
        icon_size: int | None = 32,
        icon_font: pygame.font.Font | None = None,
        icon_color: tuple[int, int, int] | None = None,
        icon_position: Literal["left", "right", "top", "bottom", "center"] = "left",
        icon_gap: int = 8,
        icon_offset_y: int = 0,
        text_visible: bool = True,
        text_position: Literal["left", "right", "top", "bottom"] | None = None,
        text_gap: int | None = None,
        content_align: Literal["center", "left", "right", "top", "bottom"] = "center",
        padding: tuple[int, int, int, int] | tuple[int, int] | int = 0,
        icon_cell_width: int | None = None,
        bg_color: tuple[int, int, int] | None = None,
        # None disables the pressed fill; the sentinel resolves to the
        # palette default at construction (live palette overrides).
        pressed_gradient: tuple[tuple[int, int, int], tuple[int, int, int]]
        | None
        | str = "default",
        gradient_dir: Literal["vertical", "horizontal"] = "vertical",
        border_top_left_radius=None,
        border_top_right_radius=None,
        border_bottom_left_radius=None,
        border_bottom_right_radius=None,
        icon_fixed_right: bool = False,
        text_offset_y: int = 0,
    ):
        if event_data is None:
            event_data = {"label": text}
        if events is None:
            events = ButtonEvents(pressed=pygame.NOEVENT, released=pygame.NOEVENT)

        super().__init__(rect, events, event_data, enabled=enabled)

        self._text = str(text)
        self.font = font or load_font(size=32, family=FontFamily.PIXEL_TYPE)
        self.color = text_color or Color.WHITE.rgb()
        self.antialias = bool(antialias) if antialias is not None else False
        self.show_border = bool(show_border)
        self.icon = icon
        self.icon_size = icon_size
        self.icon_font = icon_font or load_font(
            size=self.icon_size,
            family=FontFamily.MATERIAL_SYMBOLS,
        )
        self.icon_color = icon_color or self.color
        self.icon_position = icon_position
        self.icon_gap = max(0, int(icon_gap))
        self.icon_offset_y = int(icon_offset_y)

        self.text_visible = bool(text_visible)
        self.text_position = text_position
        self.text_gap = None if text_gap is None else max(0, int(text_gap))

        self.content_align = content_align
        self.padding = padding
        self.icon_cell_width = icon_cell_width
        self.bg_color = bg_color
        self.pressed_gradient = (
            (Color.DARK_BLUE.rgb(), Color.BLACK.rgb())
            if pressed_gradient == "default"
            else pressed_gradient
        )
        self.gradient_dir = gradient_dir

        self.border_top_left_radius = border_top_left_radius
        self.border_top_right_radius = border_top_right_radius
        self.border_bottom_left_radius = border_bottom_left_radius
        self.border_bottom_right_radius = border_bottom_right_radius

        self.icon_fixed_right = bool(icon_fixed_right)
        self.text_offset_y = int(text_offset_y)

        # ---- caches ----------------------------------------------------
        self._grad_cache_key = None
        self._grad_cache_surf: pygame.Surface | None = None

        self._text_cache_key = None
        self._text_surf: pygame.Surface | None = None

        self._icon_cache_key = None
        self._icon_surf: pygame.Surface | None = None

        self._layout_cache_key = None
        self._layout_cache = (None, None)  # (icon_pos, text_pos)

        self._compose_cache_key = None
        self._compose_cache_surf: pygame.Surface | None = None

        self._last_size = self.rect.size

        # Build initial image for DirtySprite groups.
        self._rebuild_image()

    # ----- DirtySprite integration ------------------------------------
    def _on_visual_change(self) -> None:
        self._rebuild_image()
        self.dirty = 1

    def update(self, dt: float) -> None:
        super().update(dt)
        if self.rect.size != self._last_size:
            self._last_size = self.rect.size
            self._invalidate_layout_and_composite()
            self._on_visual_change()

    # ----- rendering helpers ------------------------------------------
    @staticmethod
    def _normalize_padding(p) -> tuple[int, int, int, int]:
        """Normalize padding into (left, top, right, bottom)."""

        if isinstance(p, int):
            return (p, p, p, p)
        if isinstance(p, (tuple, list)):
            if len(p) == 2:
                return (int(p[0]), int(p[1]), int(p[0]), int(p[1]))
            if len(p) == 4:
                return (int(p[0]), int(p[1]), int(p[2]), int(p[3]))
        return (0, 0, 0, 0)

    def _inner_local_rect(self) -> pygame.Rect:
        pl, pt, pr, pb = self._normalize_padding(self.padding)
        w, h = self.rect.size
        return pygame.Rect(pl, pt, max(0, w - pl - pr), max(0, h - pt - pb))

    def _gap(self) -> int:
        return self.text_gap if self.text_gap is not None else self.icon_gap

    def _font_fingerprint(self, f: pygame.font.Font) -> tuple:
        # Using id() is sufficient within a single process; include metrics
        # to reduce accidental collisions if a font object is recreated.
        return (id(f), f.get_height(), f.get_ascent(), f.get_descent())

    def _invalidate_layout_and_composite(self) -> None:
        self._layout_cache_key = None
        self._compose_cache_key = None

    def _compute_border_color(self) -> tuple[int, int, int]:
        if not self.enabled:
            return Color.LIGHTEST_GREY.rgb()

        if self.is_pressed():
            # If text is white, use blue border for better contrast.
            return Color.BLUE.rgb() if self.color == Color.WHITE.rgb() else self.color
        return Color.LIGHT_GREY.rgb()

    def _ensure_text_surface(self) -> pygame.Surface:
        effective_color = self.color if self.enabled else Color.LIGHT_GREY.rgb()

        key = (
            self._text,
            effective_color,
            self.color,
            self.antialias,
            self._font_fingerprint(self.font),
        )
        if key != self._text_cache_key:
            self._text_surf = self.font.render(
                self._text, self.antialias, effective_color
            )
            self._text_cache_key = key
            self._invalidate_layout_and_composite()
        return self._text_surf

    def _ensure_icon_surface(self) -> pygame.Surface | None:
        if not self.icon:
            if self._icon_cache_key is not None:
                self._icon_cache_key = None
                self._icon_surf = None
                self._invalidate_layout_and_composite()
            return None

        fnt = self.icon_font or self.font

        effective_color = self.icon_color if self.enabled else Color.LIGHT_GREY.rgb()

        key = (
            self.icon,
            effective_color,
            self.icon_color,
            self.antialias,
            self._font_fingerprint(fnt),
        )
        if key != self._icon_cache_key:
            self._icon_surf = fnt.render(self.icon, self.antialias, effective_color)
            self._icon_cache_key = key
            self._invalidate_layout_and_composite()
        return self._icon_surf

    def _resolve_text_relative_pos(self) -> str:
        """Return where TEXT goes relative to ICON."""

        if self.icon_position == "center":
            return self.text_position or "bottom"

        opposite = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}
        return self.text_position or opposite[self.icon_position]

    @staticmethod
    def _anchor_xy(
        outer: pygame.Rect,
        size: tuple[int, int],
        align: Literal["center", "left", "right", "top", "bottom"],
    ) -> tuple[int, int]:
        """Anchor a block inside `outer`."""

        bw, bh = size
        # Horizontal anchoring
        if align == "left":
            x = outer.left
        elif align == "right":
            x = outer.right - bw
        else:
            x = outer.left + (outer.w - bw) // 2

        # Vertical anchoring
        if align == "top":
            y = outer.top
        elif align == "bottom":
            y = outer.bottom - bh
        else:
            y = outer.top + (outer.h - bh) // 2

        return x, y

    def _ensure_layout(
        self,
        text_surf: pygame.Surface | None,
        icon_surf: pygame.Surface | None,
    ) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        """Compute (and cache) local positions (top-left) for icon/text."""

        w, h = self.rect.size
        inner = self._inner_local_rect()
        gap = self._gap()
        rel = self._resolve_text_relative_pos()

        text_sz = text_surf.get_size() if text_surf is not None else (0, 0)
        icon_sz = icon_surf.get_size() if icon_surf is not None else (0, 0)

        key = (
            (w, h),
            inner.topleft,
            inner.size,
            self.content_align,
            self.icon_position,
            rel,
            gap,
            self.icon_cell_width,
            self.text_visible,
            text_sz,
            icon_sz,
            self.icon_fixed_right,
            self.text_offset_y,
            self.icon_offset_y,
        )
        if key == self._layout_cache_key:
            return self._layout_cache

        icon_pos: tuple[int, int] | None = None
        text_pos: tuple[int, int] | None = None

        # --- Text-only -------------------------------------------------
        if icon_surf is None:
            tw, th = text_sz
            x, y = self._anchor_xy(inner, (tw, th), self.content_align)
            text_pos = (x, y + self.text_offset_y)

        # --- Icon-only -------------------------------------------------
        elif text_surf is None or (not self.text_visible) or (self._text == ""):
            iw, ih = icon_sz
            x, y = self._anchor_xy(inner, (iw, ih), self.content_align)
            icon_pos = (x, y)

        # --- Icon + text ----------------------------------------------
        else:
            tw, th = text_sz
            iw, ih = icon_sz
            slot_w = int(self.icon_cell_width or iw)

            horizontal = rel in ("left", "right")
            if horizontal:
                total_w = tw + gap + slot_w
                total_h = max(th, ih)

                # Special fixed-right mode used by Dropdown.
                if (
                    self.icon_fixed_right
                    and rel == "left"
                    and self.icon_position != "center"
                ):
                    # text pinned to left edge, icon pinned to right edge (slot).
                    text_pos = (inner.left, inner.centery - th // 2)
                    icon_pos = (inner.right - slot_w, inner.centery - ih // 2)
                else:
                    block_x, block_y = self._anchor_xy(
                        inner, (total_w, total_h), self.content_align
                    )
                    if rel == "right":
                        # icon then text
                        icon_pos = (block_x, block_y + (total_h - ih) // 2)
                        text_pos = (
                            block_x + slot_w + gap,
                            block_y + (total_h - th) // 2,
                        )
                    else:
                        # text then icon
                        text_pos = (block_x, block_y + (total_h - th) // 2)
                        icon_pos = (block_x + tw + gap, block_y + (total_h - ih) // 2)

            else:
                total_h = th + gap + ih
                total_w = max(tw, iw)
                block_x, block_y = self._anchor_xy(
                    inner, (total_w, total_h), self.content_align
                )

                if rel == "bottom":
                    icon_pos = (block_x + (total_w - iw) // 2, block_y)
                    text_pos = (block_x + (total_w - tw) // 2, block_y + ih + gap)
                else:
                    text_pos = (block_x + (total_w - tw) // 2, block_y)
                    icon_pos = (block_x + (total_w - iw) // 2, block_y + th + gap)

            if text_pos is not None and self.text_offset_y:
                text_pos = (text_pos[0], text_pos[1] + self.text_offset_y)

            if icon_pos is not None and self.icon_offset_y:
                icon_pos = (icon_pos[0], icon_pos[1] + self.icon_offset_y)

        self._layout_cache_key = key
        self._layout_cache = (icon_pos, text_pos)
        return self._layout_cache

    # ----- composition -------------------------------------------------
    @staticmethod
    def _lerp(a: int, b: int, t: float) -> int:
        return a + int((b - a) * t)

    @staticmethod
    def _rounded_mask(size: tuple[int, int], radius: int = 4) -> pygame.Surface:
        w, h = size
        m = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(m, (255, 255, 255, 255), m.get_rect(), border_radius=radius)
        return m

    def _get_gradient_surface(
        self,
        size: tuple[int, int],
        c1: tuple[int, int, int],
        c2: tuple[int, int, int],
        horizontal: bool,
        radius: int = 4,
    ) -> pygame.Surface:
        key = (size, c1, c2, horizontal, radius)
        if key == self._grad_cache_key and self._grad_cache_surf is not None:
            return self._grad_cache_surf

        w, h = size
        grad = pygame.Surface((w, h), pygame.SRCALPHA)

        if horizontal:
            for x in range(w):
                t = x / max(1, w - 1)
                r = self._lerp(c1[0], c2[0], t)
                g = self._lerp(c1[1], c2[1], t)
                b = self._lerp(c1[2], c2[2], t)
                pygame.draw.line(grad, (r, g, b), (x, 0), (x, h - 1))
        else:
            for y in range(h):
                t = y / max(1, h - 1)
                r = self._lerp(c1[0], c2[0], t)
                g = self._lerp(c1[1], c2[1], t)
                b = self._lerp(c1[2], c2[2], t)
                pygame.draw.line(grad, (r, g, b), (0, y), (w - 1, y))

        if radius and radius > 0:
            mask = self._rounded_mask((w, h), radius)
            grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)

        self._grad_cache_key = key
        self._grad_cache_surf = grad
        return grad

    def _ensure_composed(
        self,
        text_surf: pygame.Surface | None,
        icon_surf: pygame.Surface | None,
        icon_pos: tuple[int, int] | None,
        text_pos: tuple[int, int] | None,
    ) -> pygame.Surface:
        w, h = self.rect.size
        border_color = self._compute_border_color()

        tl = self.border_top_left_radius
        tr = self.border_top_right_radius
        bl = self.border_bottom_left_radius
        br = self.border_bottom_right_radius
        any_corner = any(r is not None for r in (tl, tr, bl, br))
        if any_corner:
            tl = tl or 0
            tr = tr or 0
            bl = bl or 0
            br = br or 0

        compose_key = (
            (w, h),
            border_color,
            self.bg_color,
            self.pressed_gradient,
            self.gradient_dir,
            self.is_pressed(),
            (tl, tr, bl, br, any_corner),
            self.show_border,
            self.enabled,
            # content
            self._text_cache_key,
            self._icon_cache_key,
            icon_pos,
            text_pos,
        )
        if (
            compose_key == self._compose_cache_key
            and self._compose_cache_surf is not None
        ):
            return self._compose_cache_surf

        composed = pygame.Surface((w, h), pygame.SRCALPHA)
        rect = composed.get_rect()

        # Background fill
        if self.is_pressed() and self.pressed_gradient:
            c1, c2 = self.pressed_gradient
            horizontal = self.gradient_dir == "horizontal"
            grad = self._get_gradient_surface((w, h), c1, c2, horizontal, radius=4)
            composed.blit(grad, (0, 0))
        elif self.bg_color is not None:
            if any_corner:
                pygame.draw.rect(
                    composed,
                    self.bg_color,
                    rect,
                    border_top_left_radius=tl,
                    border_top_right_radius=tr,
                    border_bottom_left_radius=bl,
                    border_bottom_right_radius=br,
                )
            else:
                pygame.draw.rect(composed, self.bg_color, rect, border_radius=4)

        # Border
        if self.show_border:
            if any_corner:
                pygame.draw.rect(
                    composed,
                    border_color,
                    rect,
                    width=2,
                    border_top_left_radius=tl,
                    border_top_right_radius=tr,
                    border_bottom_left_radius=bl,
                    border_bottom_right_radius=br,
                )
            else:
                pygame.draw.rect(composed, border_color, rect, width=2, border_radius=4)

        # Content
        if icon_surf is not None and icon_pos is not None:
            composed.blit(icon_surf, icon_pos)
        if text_surf is not None and text_pos is not None:
            composed.blit(text_surf, text_pos)

        self._compose_cache_key = compose_key
        self._compose_cache_surf = composed
        return composed

    def _rebuild_image(self) -> None:
        # Only render text when it will be visible, or when there is no icon.
        need_text = (self.icon is None) or (self.text_visible and self._text != "")
        text_surf = self._ensure_text_surface() if need_text else None
        icon_surf = self._ensure_icon_surface()

        icon_pos, text_pos = self._ensure_layout(text_surf, icon_surf)
        composed = self._ensure_composed(text_surf, icon_surf, icon_pos, text_pos)

        # convert_alpha is faster for blitting, but only available after the
        # display is initialized.
        if pygame.display.get_surface() is not None:
            self.image = composed.convert_alpha()
        else:
            self.image = composed

    def draw(self, surface: pygame.Surface) -> None:
        """
        Manual draw helper (LayeredDirty uses `image`/`rect` directly).
        """
        surface.blit(self.image, self.rect)

    def set_text(self, text: str, *, color: tuple[int, int, int] | None = None) -> None:
        """
        Update button text (and optionally its colour) and redraw if changed.
        """
        self.text = text
        if color is not None and color != self.color:
            self.color = color
            self._text_cache_key = None
            self._invalidate_layout_and_composite()
            self._on_visual_change()

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        value = str(value)
        if value != self._text:
            self._text = value
            self._text_cache_key = None
            self._invalidate_layout_and_composite()
            self._on_visual_change()
