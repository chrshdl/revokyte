from __future__ import annotations

import pygame

from ....peripherals.display import active_profile
from ...colors import Color
from ...constants import SCREEN_WIDTH
from ...utils import su, sx, sy


class Scrollbar:
    """Elastic (iOS-style) vertical scrollbar + drag-to-scroll controller.

    Owns the scroll physics for a content region taller than its viewport:
    dragging the content follows the finger 1:1 while in bounds, dragging
    past either end rubber-bands (resistance grows with overscroll
    distance), and momentum carries the list on release — springing back to
    the nearest bound if it ends up out of range. A thumb on the right edge
    reflects the visible fraction of content and can also be dragged
    directly (or tapped) to jump-scroll.

    Geometry is authored in design-space (unscaled) px; ``draw`` and
    ``handle_event`` operate in scaled (screen/logical) coordinates, mirroring
    the rest of the widget layer.

    The caller is responsible for applying ``self.offset`` to its own
    content (e.g. ``ListItemGroup.scroll_to(offset)``) after every
    ``update()`` / ``handle_event()`` call — this class only tracks the
    scroll physics and draws the indicator, it doesn't own any content.
    """

    TRACK_WIDTH = 8
    TRACK_MARGIN_RIGHT = 16
    MIN_THUMB_HEIGHT = 32
    TRACK_HIT_PAD = 20  # extra hit-test margin around the visual track

    RUBBER_BAND_RESISTANCE = 5.0
    FRICTION_DECAY = 3.5  # 1/s — higher stops momentum sooner
    SPRING_STIFFNESS = 120  # 90.0  # 1/s^2 — pulls an out-of-bounds offset back
    SPRING_DAMPING = 18.0  # 1/s
    DRAG_THRESHOLD = 12  # design-px finger movement before a tap becomes a drag
    VELOCITY_EPSILON = 2.0  # design-px/s below which momentum is considered stopped

    def __init__(
        self,
        viewport_top: float,
        viewport_height: float,
        content_height: float,
        track_color=(15, 30, 60),
        thumb_color=None,
        track_margin_bottom: float = 0.0,
    ):
        self.viewport_top = viewport_top
        self.viewport_height = viewport_height
        self.content_height = content_height
        self.track_color = track_color
        self.thumb_color = thumb_color or Color.BLUE.rgb()
        # Shortens only the visual track (and its hit/thumb geometry) at the
        # bottom, in design px — the scroll viewport and range are untouched.
        # Lets the track keep the same breathing room from the screen bottom
        # as viewport_top gives it from the chrome above.
        self.track_margin_bottom = track_margin_bottom

        self.offset = 0.0
        self._velocity = 0.0

        # thumb-drag: dragging the visible track/thumb directly
        self._thumb_dragging = False
        self._thumb_finger_id = None

        # content-drag: tap-vs-drag disambiguated gesture over the row content
        self._gesture_id = None
        self._gesture_start: tuple[float, float] | None = None
        self._gesture_dragging = False
        self._gesture_base_offset = 0.0
        self._last_touch_y = 0.0
        self._last_touch_t = 0.0

    # ------------------------------------------------------------------
    # geometry
    # ------------------------------------------------------------------
    @property
    def max_offset(self) -> float:
        return max(0.0, self.content_height - self.viewport_height)

    @property
    def is_scrollable(self) -> bool:
        return self.content_height > self.viewport_height

    def set_content_height(self, height: float) -> None:
        self.content_height = height
        self.offset = max(0.0, min(self.max_offset, self.offset))

    def _track_rect(self) -> pygame.Rect:
        w = su(self.TRACK_WIDTH)
        x = sx(SCREEN_WIDTH - self.TRACK_MARGIN_RIGHT) - w
        h = sy(self.viewport_height - self.track_margin_bottom)
        return pygame.Rect(x, sy(self.viewport_top), w, h)

    def _track_hit_rect(self) -> pygame.Rect:
        pad = su(self.TRACK_HIT_PAD)
        return self._track_rect().inflate(pad * 2, 0)

    def viewport_rect(self) -> pygame.Rect:
        return pygame.Rect(
            0, sy(self.viewport_top), sx(SCREEN_WIDTH), sy(self.viewport_height)
        )

    # ------------------------------------------------------------------
    # rubber banding
    # ------------------------------------------------------------------
    def _rubber_band(self, overscroll: float) -> float:
        return overscroll / self.RUBBER_BAND_RESISTANCE

    def _clamp_elastic(self, raw_offset: float) -> float:
        if raw_offset < 0:
            return self._rubber_band(raw_offset)
        if raw_offset > self.max_offset:
            return self.max_offset + self._rubber_band(raw_offset - self.max_offset)
        return raw_offset

    # ------------------------------------------------------------------
    # physics: momentum decay + spring-back, advanced once per frame
    # ------------------------------------------------------------------
    def update(self, dt: float) -> None:
        if self._thumb_dragging or self._gesture_dragging or dt <= 0:
            return
        if self._velocity == 0.0 and 0.0 <= self.offset <= self.max_offset:
            return

        out_of_bounds = self.offset < 0 or self.offset > self.max_offset
        if out_of_bounds:
            target = 0.0 if self.offset < 0 else self.max_offset
            accel = (target - self.offset) * self.SPRING_STIFFNESS
            self._velocity += accel * dt
            self._velocity *= max(0.0, 1 - self.SPRING_DAMPING * dt)
        else:
            self._velocity *= max(0.0, 1 - self.FRICTION_DECAY * dt)
            if abs(self._velocity) < self.VELOCITY_EPSILON:
                self._velocity = 0.0

        self.offset += self._velocity * dt

        if not out_of_bounds and self._velocity == 0.0:
            self.offset = max(0.0, min(self.max_offset, self.offset))

    # ------------------------------------------------------------------
    # gesture handling
    # ------------------------------------------------------------------
    def handle_event(self, event, rows) -> bool:
        """Route a touch/mouse event through thumb-drag and content-drag
        disambiguation. ``rows`` is anything with ``handle_event(event)``
        (e.g. a ``ListItemGroup``) that owns the pressable widgets in the
        scrollable region — taps are forwarded to it so button/dropdown
        presses still work; a confirmed drag cancels the pressed visual and
        takes over scrolling instead.

        Returns True if this call fully handled the event (caller should not
        dispatch it again).
        """
        if not self.is_scrollable:
            return False

        if event.type in (pygame.FINGERDOWN, pygame.MOUSEBUTTONDOWN):
            pos = active_profile().to_logical(event)
            if pos is None:
                return False
            if self._track_hit_rect().collidepoint(pos):
                self._begin_thumb_drag(event, pos)
                return True
            if event.type == pygame.FINGERDOWN and self.viewport_rect().collidepoint(
                pos
            ):
                rows.handle_event(event)
                self._gesture_id = event.finger_id
                self._gesture_start = pos
                self._gesture_dragging = False
                return True
            return False

        if self._thumb_dragging:
            return self._continue_thumb_drag(event, rows)

        if self._gesture_id is not None:
            return self._continue_content_drag(event, rows)

        return False

    def _begin_thumb_drag(self, event, pos) -> None:
        self._thumb_dragging = True
        self._thumb_finger_id = getattr(event, "finger_id", 0)
        self._velocity = 0.0
        self._scrub_thumb_to(pos[1])

    def _scrub_thumb_to(self, y: float) -> None:
        track = self._track_rect()
        span = max(1, track.height)
        frac = max(0.0, min(1.0, (y - track.top) / span))
        self.offset = frac * self.max_offset

    def _continue_thumb_drag(self, event, rows) -> bool:
        finger_id = getattr(event, "finger_id", 0)
        if finger_id != self._thumb_finger_id:
            return False
        if event.type in (pygame.FINGERMOTION, pygame.MOUSEMOTION):
            pos = active_profile().to_logical(event)
            if pos:
                self._scrub_thumb_to(pos[1])
            return True
        if event.type in (pygame.FINGERUP, pygame.MOUSEBUTTONUP):
            self._thumb_dragging = False
            self._thumb_finger_id = None
            return True
        return False

    def _continue_content_drag(self, event, rows) -> bool:
        if event.type != pygame.FINGERMOTION and event.type != pygame.FINGERUP:
            return False
        if event.finger_id != self._gesture_id:
            return False

        pos = active_profile().to_logical(event)

        if event.type == pygame.FINGERMOTION:
            if pos is None:
                return True
            now = pygame.time.get_ticks() / 1000.0
            if not self._gesture_dragging:
                dx = pos[0] - self._gesture_start[0]
                dy = pos[1] - self._gesture_start[1]
                if max(abs(dx), abs(dy)) > su(self.DRAG_THRESHOLD):
                    self._gesture_dragging = True
                    self._gesture_base_offset = self.offset
                    self._last_touch_y = pos[1]
                    self._last_touch_t = now
                    self._cancel_press(rows)
            if self._gesture_dragging:
                dt = max(1e-3, now - self._last_touch_t)
                self._velocity = -(pos[1] - self._last_touch_y) / dt
                self._last_touch_y = pos[1]
                self._last_touch_t = now

                delta = self._gesture_start[1] - pos[1]
                self.offset = self._clamp_elastic(self._gesture_base_offset + delta)
            return True

        # FINGERUP
        if not self._gesture_dragging:
            rows.handle_event(event)  # confirmed tap: deliver the release
        self._gesture_id = None
        self._gesture_start = None
        self._gesture_dragging = False
        return True

    def _cancel_press(self, rows) -> None:
        """Send an out-of-bounds FINGERUP so any pressed row widget resets."""
        cancel = pygame.event.Event(
            pygame.FINGERUP,
            finger_id=self._gesture_id,
            touch_id=0,
            x=-1.0,
            y=-1.0,
            dx=0.0,
            dy=0.0,
            pressure=0.0,
        )
        rows.handle_event(cancel)

    # ------------------------------------------------------------------
    # drawing
    # ------------------------------------------------------------------
    def draw(self, surface) -> None:
        if not self.is_scrollable:
            return

        track = self._track_rect()
        pygame.draw.rect(
            surface, self.track_color, track, border_radius=track.width // 2
        )

        visible_fraction = self.viewport_height / self.content_height
        thumb_h = max(su(self.MIN_THUMB_HEIGHT), int(track.height * visible_fraction))
        frac = (
            0.0
            if self.max_offset <= 0
            else max(0.0, min(1.0, self.offset / self.max_offset))
        )
        thumb_top = track.top + int((track.height - thumb_h) * frac)
        thumb = pygame.Rect(track.x, thumb_top, track.width, thumb_h)
        pygame.draw.rect(
            surface, self.thumb_color, thumb, border_radius=track.width // 2
        )
