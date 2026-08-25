from __future__ import annotations

import math

import pygame

from ....peripherals.display import active_profile
from ...colors import Color
from ...skins import active_skin

# Gesture id for mouse-driven content drags; finger ids are ints, so a
# sentinel object can never collide with one.
_MOUSE_GESTURE = object()


class Scrollbar:
    """Elastic (iOS-style) vertical scrollbar + drag-to-scroll controller.

    Owns the scroll physics for a content region taller than its viewport:
    dragging the content follows the finger 1:1 while in bounds, dragging
    past either end rubber-bands (resistance grows with overscroll
    distance), and momentum carries the list on release — springing back to
    the nearest bound if it ends up out of range. A thumb on the right edge
    reflects the visible fraction of content and can also be dragged
    directly (or tapped) to jump-scroll.

    Geometry, ``self.offset``, and event coordinates are all native
    (logical) px — callers pass values derived from ``active_skin()``, and
    the track/thumb styling comes from ``skin.style.scrollbar``. One unit
    end to end: finger deltas from ``to_logical`` add directly onto the
    offset (the old design-px offset under-scrolled content drags on the
    scaled panels).

    The caller is responsible for applying ``self.offset`` to its own
    content (e.g. ``ListItemGroup.scroll_to(offset)``) after every
    ``update()`` / ``handle_event()`` call — this class only tracks the
    scroll physics and draws the indicator, it doesn't own any content.
    """

    RUBBER_BAND_RESISTANCE = 10.0
    FRICTION_DECAY = 3.5  # 1/s — higher stops momentum sooner
    # Slightly underdamped pair: settles an out-of-bounds offset in ~400 ms
    # (~half of the previous 120/18 tuning) with sub-pixel overshoot. Note
    # the discrete integrator (vel *= 1 - damping*dt at 60 fps) makes large
    # damping values crawl — don't raise damping without re-simulating.
    SPRING_STIFFNESS = 300  # 1/s^2 — pulls an out-of-bounds offset back
    SPRING_DAMPING = 22.0  # 1/s
    VELOCITY_EPSILON = 2.0  # px/s below which momentum is considered stopped
    # With snapping enabled: once free momentum decays below this, the spring
    # takes over and glides to the nearest snap point (px/s).
    SNAP_VELOCITY = 250.0
    # Release velocity cap (px/s). Touch timestamps can degenerate
    # (two motion events in the same tick), producing absurd flings that
    # ricochet between the bounds before the spring can catch them.
    MAX_FLING_VELOCITY = 3000.0

    def __init__(
        self,
        viewport_top: float,
        viewport_height: float,
        content_height: float,
        track_color=(15, 30, 60),
        thumb_color=None,
        track_margin_bottom: float = 0.0,
        snap_interval: float = 0.0,
    ):
        self.viewport_top = viewport_top
        self.viewport_height = viewport_height
        self.content_height = content_height
        self.track_color = track_color
        self.thumb_color = (
            thumb_color
            or Color[active_skin().style.scrollbar.thumb_color].rgb()
        )
        # Shortens only the visual track (and its hit/thumb geometry) at the
        # bottom, in native px — the scroll viewport and range are untouched.
        # Lets the track keep the same breathing room from the screen bottom
        # as viewport_top gives it from the chrome above.
        self.track_margin_bottom = track_margin_bottom
        # > 0: after a release the offset comes to rest on a multiple of this
        # (native px, typically the row pitch) so no row is left half-cut.
        # The bounds always win over a snap point.
        self.snap_interval = snap_interval

        self.offset = 0.0
        self._velocity = 0.0
        # Latched snap destination for the current glide. Chosen ONCE when
        # the spring phase engages — recomputing per frame would combine
        # with the direction bias into an escalator (each crossed boundary
        # re-targets the next one, and the spring chases it to the end).
        self._snap_goal: float | None = None

        # thumb-drag: dragging the visible track/thumb directly
        self._thumb_dragging = False
        self._thumb_finger_id = None

        # content-drag: tap-vs-drag disambiguated gesture over the row
        # content, driven by touch or mouse alike
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
    def in_motion(self) -> bool:
        """Is the scroll offset actually changing right now?

        Distinct from :attr:`is_scrollable`, which only says the content
        overflows. A settings list that overflows but is sitting still needs
        no per-frame repaint — and on the 7" panel it overflows permanently,
        so conflating the two made every stationary Setup frame a full-screen
        flush (22x the cost of a dirty-rect frame, measured on a Pi 4).

        Velocity is the reliable signal: update() zeroes it on settle, while
        _snap_goal is re-derived and cleared on alternate frames and would
        flap. A tap that never crosses the drag threshold leaves
        _gesture_dragging False, so tapping a row stays on the cheap path.
        """
        return bool(
            self._thumb_dragging or self._gesture_dragging or self._velocity
        )

    def reset(self) -> None:
        """Back to the top, with no gesture or glide in flight.

        The owning view outlives the state that scrolled it, so re-entering a
        settings screen would otherwise land wherever the last visit left off
        — mid-list, or still coasting.
        """
        self.offset = 0.0
        self._velocity = 0.0
        self._snap_goal = None
        self._thumb_dragging = False
        self._thumb_finger_id = None
        self._gesture_id = None
        self._gesture_start = None
        self._gesture_dragging = False
        self._gesture_base_offset = 0.0
        self._last_touch_y = 0.0
        self._last_touch_t = 0.0

    @property
    def is_scrollable(self) -> bool:
        return self.content_height > self.viewport_height

    def set_content_height(self, height: float) -> None:
        self.content_height = height
        self.offset = max(0.0, min(self.max_offset, self.offset))

    def _track_rect(self) -> pygame.Rect:
        skin = active_skin()
        style = skin.style.scrollbar
        w = style.track_width
        x = skin.width - style.track_margin_right - w
        h = round(self.viewport_height - self.track_margin_bottom)
        return pygame.Rect(x, round(self.viewport_top), w, h)

    def _track_hit_rect(self) -> pygame.Rect:
        pad = active_skin().style.scrollbar.track_hit_pad
        return self._track_rect().inflate(pad * 2, 0)

    def viewport_rect(self) -> pygame.Rect:
        return pygame.Rect(
            0,
            round(self.viewport_top),
            active_skin().width,
            round(self.viewport_height),
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
    # physics: momentum decay + snap/spring-back, advanced once per frame
    # ------------------------------------------------------------------
    def _snap_target(self) -> float | None:
        """Snap point in the direction of travel, so a gliding list is never
        pulled backwards; on a dead stop, the nearest one. The list end is a
        rest point too, but it must not override the travel direction — only
        the dead-stop case weighs it against the nearest multiple. None when
        snapping is off."""
        if self.snap_interval <= 0:
            return None
        q = self.offset / self.snap_interval
        if self._velocity > self.VELOCITY_EPSILON:
            # Heading for the end: past the last multiple, the end itself.
            return min(math.ceil(q) * self.snap_interval, self.max_offset)
        if self._velocity < -self.VELOCITY_EPSILON:
            return max(math.floor(q) * self.snap_interval, 0.0)
        target = max(0.0, min(self.max_offset, round(q) * self.snap_interval))
        if abs(self.max_offset - self.offset) < abs(target - self.offset):
            target = self.max_offset
        return target

    def update(self, dt: float) -> None:
        if self._thumb_dragging or self._gesture_dragging or dt <= 0:
            return

        out_of_bounds = self.offset < 0 or self.offset > self.max_offset
        target = None
        if out_of_bounds:
            self._snap_goal = None
            target = 0.0 if self.offset < 0 else self.max_offset
        elif abs(self._velocity) < self.SNAP_VELOCITY:
            if self._snap_goal is None:
                self._snap_goal = self._snap_target()
            target = self._snap_goal
        else:
            self._snap_goal = None

        if target is None:
            # Free momentum: friction decay only.
            if self._velocity == 0.0:
                return
            self._velocity *= max(0.0, 1 - self.FRICTION_DECAY * dt)
            if abs(self._velocity) < self.VELOCITY_EPSILON:
                self._velocity = 0.0
            before = self.offset
            self.offset += self._velocity * dt
            # Momentum hitting a bound gets the same rubber-band absorption
            # as a finger overpull — otherwise a hard flick shoots far past
            # the end at full speed and rebounds a whole row back inward.
            if self.offset > self.max_offset and before <= self.max_offset:
                over = self.offset - self.max_offset
                self.offset = self.max_offset + self._rubber_band(over)
                self._velocity /= self.RUBBER_BAND_RESISTANCE
            elif self.offset < 0.0 and before >= 0.0:
                self.offset = self._rubber_band(self.offset)
                self._velocity /= self.RUBBER_BAND_RESISTANCE
            if self._velocity == 0.0:
                self.offset = max(0.0, min(self.max_offset, self.offset))
            return

        if (
            abs(self.offset - target) < 0.5
            and abs(self._velocity) < self.VELOCITY_EPSILON
        ):
            self.offset = target
            self._velocity = 0.0
            self._snap_goal = None
            return

        accel = (target - self.offset) * self.SPRING_STIFFNESS
        self._velocity += accel * dt
        self._velocity *= max(0.0, 1 - self.SPRING_DAMPING * dt)
        before = self.offset
        self.offset += self._velocity * dt
        if out_of_bounds and (before - target) * (self.offset - target) <= 0:
            # The rubber-band return reached the bound: capture it dead
            # instead of letting residual speed bounce into the content.
            self.offset = target
            self._velocity = 0.0
            self._snap_goal = None

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
            if self._is_touch_synthesized_mouse(event):
                # The real FINGER* stream drives the gesture; acting on the
                # mouse events SDL synthesizes from it would double-start.
                return False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button != 1:
                return False
            pos = active_profile().to_logical(event)
            if pos is None:
                return False
            if self._track_hit_rect().collidepoint(pos):
                self._begin_thumb_drag(event, pos)
                return True
            if self.viewport_rect().collidepoint(pos):
                rows.handle_event(event)
                self._gesture_id = self._gesture_event_id(event)
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
        self._snap_goal = None
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

    @staticmethod
    def _is_touch_synthesized_mouse(event) -> bool:
        return getattr(event, "touch", False)

    @staticmethod
    def _gesture_event_id(event):
        return getattr(event, "finger_id", _MOUSE_GESTURE)

    def _continue_content_drag(self, event, rows) -> bool:
        is_motion = event.type in (pygame.FINGERMOTION, pygame.MOUSEMOTION)
        is_release = event.type in (pygame.FINGERUP, pygame.MOUSEBUTTONUP)
        if not (is_motion or is_release):
            return False
        if self._is_touch_synthesized_mouse(event):
            return False
        if self._gesture_event_id(event) != self._gesture_id:
            return False

        pos = active_profile().to_logical(event)

        if is_motion:
            if pos is None:
                return True
            now = pygame.time.get_ticks() / 1000.0
            if not self._gesture_dragging:
                dx = pos[0] - self._gesture_start[0]
                dy = pos[1] - self._gesture_start[1]
                threshold = active_skin().style.scrollbar.drag_threshold
                if max(abs(dx), abs(dy)) > threshold:
                    self._gesture_dragging = True
                    self._snap_goal = None
                    self._gesture_base_offset = self.offset
                    self._last_touch_y = pos[1]
                    self._last_touch_t = now
                    self._cancel_press(rows)
            if self._gesture_dragging:
                dt = max(1e-3, now - self._last_touch_t)
                raw_velocity = -(pos[1] - self._last_touch_y) / dt
                self._velocity = max(
                    -self.MAX_FLING_VELOCITY,
                    min(self.MAX_FLING_VELOCITY, raw_velocity),
                )
                self._last_touch_y = pos[1]
                self._last_touch_t = now

                delta = self._gesture_start[1] - pos[1]
                self.offset = self._clamp_elastic(self._gesture_base_offset + delta)
            return True

        # release (FINGERUP / MOUSEBUTTONUP)
        if not self._gesture_dragging:
            rows.handle_event(event)  # confirmed tap: deliver the release
        self._gesture_id = None
        self._gesture_start = None
        self._gesture_dragging = False
        return True

    def _cancel_press(self, rows) -> None:
        """Send an out-of-bounds release so any pressed row widget resets,
        matching the modality that pressed it (Button tracks pointer ids)."""
        if self._gesture_id is _MOUSE_GESTURE:
            cancel = pygame.event.Event(
                pygame.MOUSEBUTTONUP, pos=(-1, -1), button=1, touch=False
            )
        else:
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
        thumb_h = max(
            active_skin().style.scrollbar.min_thumb_height,
            int(track.height * visible_fraction),
        )
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
