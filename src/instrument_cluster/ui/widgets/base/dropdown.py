from __future__ import annotations

from typing import Any, Iterable

import pygame
from pygame.sprite import DirtySprite, LayeredDirty

from ...colors import Color
from ...utils import su
from .button import Button, ButtonEvents, ButtonState

TEXT_LEFT_PAD = 32

# Radio button drawn to the left of each option's label (see _DropdownOption
# ._draw_radio): its ring aligns with the header's value-text column, and the
# label follows RADIO_GAP after it.
RADIO_LEFT_X = 24  # minimum radio inset for headers with a smaller pad
RADIO_DIAMETER = 32
RADIO_RING_WIDTH = 3
RADIO_DOT_DIAMETER = 14
RADIO_GAP = 16


class _DropdownOption(Button):
    """Internal menu item sprite for Dropdown."""

    def __init__(
        self,
        parent: "Dropdown",
        opt_idx: int,
        rect: pygame.Rect,
        label: str,
        is_selected: bool = False,
    ):
        self._parent = parent
        self._opt_idx = opt_idx
        self._is_selected = is_selected

        super().__init__(
            rect=rect,
            text=label,
            events=ButtonEvents(pressed=pygame.NOEVENT, released=pygame.NOEVENT),
            event_data={},
            font=parent.font,
            text_color=Color.WHITE.rgb(),
            antialias=parent.antialias,
            icon=None,
            text_visible=True,
            content_align="left",
            padding=(su(parent.option_text_left_pad), su(20), su(20), su(20)),
            # The radio is drawn at the rect's exact vertical center, so the
            # text must stay centered too (no header-style baseline nudge).
            text_offset_y=0,
            bg_color=parent._open_bg_color,
            pressed_gradient=None,
            show_border=False,
            border_top_left_radius=0,
            border_top_right_radius=0,
            border_bottom_left_radius=0,
            border_bottom_right_radius=0,
        )

        self._normal_bg = parent._open_bg_color
        self._pressed_bg = parent._pressed_bg_color

    def _rebuild_image(self) -> None:
        super()._rebuild_image()
        # _rebuild_image() may hand back a cached surface (when the display
        # isn't initialized); copy before drawing so we never mutate it.
        self.image = self.image.copy()
        self._draw_radio()

    def _draw_radio(self) -> None:
        d = su(RADIO_DIAMETER)
        radio_left = self._parent.option_text_left_pad - RADIO_DIAMETER - RADIO_GAP
        cx = su(radio_left) + d // 2
        cy = self.rect.height // 2
        color = Color.BLUE.rgb() if self._is_selected else Color.WHITE.rgb()
        pygame.draw.circle(
            self.image, color, (cx, cy), d // 2, width=su(RADIO_RING_WIDTH)
        )
        if self._is_selected:
            dot_r = su(RADIO_DOT_DIAMETER) // 2
            pygame.draw.circle(self.image, color, (cx, cy), dot_r)

    def _set_bg(self, c: tuple[int, int, int]) -> None:
        if self.bg_color != c:
            self.bg_color = c
            self._invalidate_layout_and_composite()
            self._on_visual_change()

    def handle_event(self, event) -> None:
        pid = self._pointer_id(event)
        xy = self._event_xy(event)
        if pid is None or xy is None:
            return

        prev_state = self.state
        super().handle_event(event)

        # Pressed visual
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
            if self.state == ButtonState.PRESSED:
                self._set_bg(self._pressed_bg)

        # Release / cancel visual
        if event.type in (pygame.MOUSEBUTTONUP, pygame.FINGERUP):
            if (
                prev_state in (ButtonState.PRESSED, ButtonState.LONGPRESSED)
                and self.state == ButtonState.RELEASED
            ):
                self._parent._on_option_chosen(self._opt_idx)
                return

            self._set_bg(self._normal_bg)


class Dropdown(Button):
    """
    Dropdown widget:
    - Header is a sprite
    - Menu options are sprites added/removed from the same LayeredDirty group
    """

    SCRIM_LAYER = 900
    DROPDOWN_HEADER_OPEN_LAYER = 950
    DROPDOWN_MENU_LAYER = 1000

    def __init__(
        self,
        rect,
        options: Iterable[Any],
        events,
        event_data=None,
        selected_index: int = 0,
        font=None,
        text_color=None,
        *,
        menu_layer: int = DROPDOWN_MENU_LAYER,
        menu_pitch: int | None = None,
        closed_bg_color: tuple[int, int, int] = Color.BLACK.rgb(),
        open_bg_color: tuple[int, int, int] = Color.DARKEST_GREY.rgb(),
        pressed_bg_color: tuple[int, int, int] = Color.DARKER_GREY.rgb(),
        text_left_pad: int = TEXT_LEFT_PAD,
        menu_separator_color: tuple[int, int, int] | None = None,
        menu_separator_width: int = 1,
    ):
        self.options = list(options)
        self.selected_index = int(selected_index)
        # Vertical distance (scaled px) between the header top and each
        # successive menu option top. Lets an open menu align with a row grid
        # (e.g. the setup view's ListItems). None keeps the compact default.
        self.menu_pitch = menu_pitch

        self._closed_bg_color = closed_bg_color
        self._open_bg_color = open_bg_color
        self._pressed_bg_color = pressed_bg_color
        # When set, the list's separator lines crossing the open menu are
        # repainted onto the scrim at each cell boundary (design px width).
        self.menu_separator_color = menu_separator_color
        self.menu_separator_width = menu_separator_width

        # Menu options place the radio ring on the header's value-text column
        # (so it takes the value text's place when the menu opens) and indent
        # their label RADIO_GAP after it. The floor keeps the radio inside
        # the row for headers with the small default pad.
        self.option_text_left_pad = (
            max(text_left_pad, RADIO_LEFT_X) + RADIO_DIAMETER + RADIO_GAP
        )

        label = self._label_for_index(self.selected_index)

        super().__init__(
            rect=rect,
            text=label,
            events=events,
            event_data=event_data,
            show_border=False,
            pressed_gradient=None,
            font=font,
            text_color=text_color or Color.WHITE.rgb(),
            icon="\ue313",
            icon_size=46,
            icon_position="right",
            icon_offset_y=su(4),
            content_align="left",
            padding=(su(text_left_pad), su(20), su(20), su(20)),
            icon_fixed_right=True,
            text_offset_y=su(4),
            border_top_left_radius=4,
            border_top_right_radius=4,
            border_bottom_left_radius=4,
            border_bottom_right_radius=4,
            bg_color=self._closed_bg_color,
        )

        self.open = False
        self._menu_layer = int(menu_layer)
        self._group: LayeredDirty | None = None
        self._menu_sprites: list[_DropdownOption] = []
        self._scrim: DirtySprite | None = None
        self._base_layer: int | None = None
        self._open_header_layer: int = Dropdown.DROPDOWN_HEADER_OPEN_LAYER

    @classmethod
    def handle_priority_event(
        cls, event: pygame.event.Event, dropdowns: Iterable[Dropdown]
    ) -> bool:
        """
        Global handler for a collection of dropdowns.
        Handles forwarding events to open menus and closing them if a click occurs outside.
        Returns True if the event was consumed.
        """
        pointer_types = (
            pygame.MOUSEBUTTONDOWN,
            pygame.MOUSEBUTTONUP,
            pygame.MOUSEMOTION,
            pygame.FINGERDOWN,
            pygame.FINGERUP,
            pygame.FINGERMOTION,
        )

        if event.type not in pointer_types:
            return False

        # We use any dropdown to access the helper method _event_xy
        # (Assuming all dropdowns exist in the same coordinate space)
        first_dd = next(iter(dropdowns), None)
        if not first_dd:
            return False

        xy = first_dd._event_xy(event)
        if xy is None:
            return False

        open_dropdowns = [d for d in dropdowns if d.open]
        if not open_dropdowns:
            return False

        # 1. Forward to open dropdowns so internal items can highlight/select
        for d in open_dropdowns:
            d.handle_event(event)

        # 2. If click/tap DOWN happens outside all open dropdowns, close them
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
            if not any(d.hit_test(xy) for d in open_dropdowns):
                for d in open_dropdowns:
                    d._set_open(False)
                # We return True because we handled the "outside click"
                # and likely want to swallow this event
                return True

        # Return True to indicate that an open dropdown absorbed the pointer interaction
        return True

    # -----------------------------------------------------------------
    # Binding
    # -----------------------------------------------------------------

    def bind_group(
        self,
        group: LayeredDirty,
        *,
        menu_layer: int | None = None,
        open_header_layer: int | None = None,
    ) -> None:
        self._group = group
        if menu_layer is not None:
            self._menu_layer = int(menu_layer)
        if open_header_layer is not None:
            self._open_header_layer = int(open_header_layer)

        try:
            self._base_layer = group.get_layer_of_sprite(self)
        except Exception:
            self._base_layer = None

    # -----------------------------------------------------------------
    # Labels / selection
    # -----------------------------------------------------------------

    @staticmethod
    def _label_for_value(value: Any) -> str:
        v = getattr(value, "value", None)
        return str(v) if isinstance(v, str) else str(value)

    def _label_for_index(self, idx: int) -> str:
        if 0 <= idx < len(self.options):
            return self._label_for_value(self.options[idx])
        return ""

    def _on_option_chosen(self, opt_idx: int) -> None:
        self.set_selected_index(opt_idx, fire_event=True)

    def set_selected_index(self, idx: int, fire_event: bool = False) -> None:
        idx = int(idx)
        if not (0 <= idx < len(self.options)):
            return

        self.selected_index = idx
        value = self.options[idx]
        self.text = self._label_for_value(value)

        self._set_open(False)

        if fire_event and getattr(self.events, "selected", None):
            data = dict(self.event_data or {})
            data.update({"selected_index": idx, "mode": value})
            pygame.event.post(pygame.event.Event(self.events.selected, data))

    # -----------------------------------------------------------------
    # Visual helpers
    # -----------------------------------------------------------------

    def _set_bg(self, c: tuple[int, int, int]) -> None:
        if self.bg_color != c:
            self.bg_color = c
            self._invalidate_layout_and_composite()
            self._on_visual_change()

    # -----------------------------------------------------------------
    # Open / close lifecycle
    # -----------------------------------------------------------------

    def _set_open(self, is_open: bool) -> None:
        is_open = bool(is_open)
        if self.open == is_open:
            return

        self.open = is_open

        if self._group is not None:
            if self.open:
                if self._base_layer is None:
                    try:
                        self._base_layer = self._group.get_layer_of_sprite(self)
                    except Exception:
                        self._base_layer = 0
                self._group.change_layer(self, self._open_header_layer)
            else:
                if self._base_layer is not None:
                    self._group.change_layer(self, self._base_layer)

        if self.open:
            self._set_bg(self._open_bg_color)
            self.border_bottom_left_radius = 0
            self.border_bottom_right_radius = 0
            self._spawn_menu_sprites()
        else:
            self._despawn_menu_sprites()
            self.border_bottom_left_radius = 4
            self.border_bottom_right_radius = 4
            self._set_bg(self._closed_bg_color)

    def _spawn_menu_sprites(self) -> None:
        if self._group is None:
            return
        if self._menu_sprites:
            return

        pairs = self.get_option_rects()
        if not pairs:
            return

        sprites: list[_DropdownOption] = []
        for opt_idx, rect in pairs:
            label = self._label_for_value(self.options[opt_idx])
            is_selected = opt_idx == self.selected_index
            sprites.append(_DropdownOption(self, opt_idx, rect, label, is_selected))

        # round bottom corners on last option only
        last = sprites[-1]
        last.border_bottom_left_radius = 4
        last.border_bottom_right_radius = 4
        last._on_visual_change()

        # Opaque scrim under the whole open footprint (header + options) so
        # widgets behind the menu can't show through the header/option gap or
        # the rounded corner notches.
        footprint = self.rect.unionall([r for _, r in pairs])
        scrim = DirtySprite()
        scrim.image = pygame.Surface(footprint.size)
        scrim.image.fill(Color.BLACK.rgb())
        scrim.rect = footprint
        if self.menu_separator_color is not None:
            # The scrim blanks whatever runs beneath the open menu, including
            # the list's separator lines crossing the gaps between the header
            # and option sprites — repaint them so they stay visible.
            cells = [self.rect] + [r for _, r in pairs]
            for prev_r, next_r in zip(cells, cells[1:]):
                y = (prev_r.bottom + next_r.top) // 2 - footprint.top
                pygame.draw.line(
                    scrim.image,
                    self.menu_separator_color,
                    (0, y),
                    (footprint.width, y),
                    max(1, su(self.menu_separator_width)),
                )
        self._group.add(scrim, layer=Dropdown.SCRIM_LAYER)
        self._scrim = scrim

        for s in sprites:
            self._group.add(s, layer=self._menu_layer)

        self._menu_sprites = sprites

    def _despawn_menu_sprites(self) -> None:
        if not self._menu_sprites:
            return
        if self._group is not None:
            for s in self._menu_sprites:
                self._group.remove(s)
        for s in self._menu_sprites:
            s.kill()
        self._menu_sprites.clear()

        if self._scrim is not None:
            self._scrim.kill()
            self._scrim = None

    # -----------------------------------------------------------------
    # Input handling
    # -----------------------------------------------------------------

    def _click_is_outside_dropdown(self, xy: tuple[int, int]) -> bool:
        if self.rect.collidepoint(xy):
            return False
        return not any(s.rect.collidepoint(xy) for s in self._menu_sprites)

    def handle_event(self, event) -> None:
        pid = self._pointer_id(event)
        xy = self._event_xy(event)

        if pid is None or xy is None:
            return

        # 1. Forward events to open menu options
        if self.open and self._menu_sprites:
            for s in self._menu_sprites:
                s.handle_event(event)

            # Close if clicked outside
            if event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                if self._click_is_outside_dropdown(xy):
                    self._set_open(False)
                    return  # Stop processing if we closed it

        # 2. Header Logic
        # We only want to trigger the header's button logic (super) if the click
        # is actually ON the header. Because hit_test() returns True for menu
        # items too, we must restrict this block manually to the header rect.
        is_header_interaction = self.rect.collidepoint(xy)

        # Track state BEFORE super updates it (for release detection)
        was_pressed_by_this_pointer = (
            self.state in (ButtonState.PRESSED, ButtonState.LONGPRESSED)
            and getattr(self, "_active_pointer", None) == pid
        )
        is_release = event.type in (pygame.MOUSEBUTTONUP, pygame.FINGERUP)

        # A press that started on the header must also see its release when the
        # pointer was dragged off the header before letting go — otherwise the
        # header stays stuck in the pressed color owning the pointer.
        if is_header_interaction or (was_pressed_by_this_pointer and is_release):
            # Handle header visual override for DOWN
            if event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                self._set_bg(self._pressed_bg_color)

            # Let base Button class update state (IDLE->PRESSED, PRESSED->RELEASED)
            super().handle_event(event)

            # Handle Release / Click Logic
            if is_release:
                # Restore background
                self._set_bg(
                    self._open_bg_color if self.open else self._closed_bg_color
                )

                # Only toggle when the release lands on the header; a release
                # after dragging off just cancels the press.
                if was_pressed_by_this_pointer and is_header_interaction:
                    # A second header tap closes the menu without firing
                    # `selected` — nothing was chosen, and listeners (e.g.
                    # the telemetry row's IP-entry flow) must not react as
                    # if the current option had been picked again.
                    self._set_open(not self.open)

    # -----------------------------------------------------------------
    # Geometry
    # -----------------------------------------------------------------

    def get_option_rects(self) -> list[tuple[int, pygame.Rect]]:
        rects: list[tuple[int, pygame.Rect]] = []
        x, y, w, h = self.rect
        menu_offset_y = 10

        for idx in range(len(self.options)):
            row = idx + 1
            if self.menu_pitch is not None:
                # Each option mirrors the header's rect one grid cell further
                # down, inheriting whatever clearance the header keeps from
                # the separator lines (see SetupView._row_dropdown) so option
                # backgrounds never cover them either.
                r = pygame.Rect(x, y + row * self.menu_pitch, w, h)
            else:
                r = pygame.Rect(x, y + row * h + menu_offset_y, w, h)
            rects.append((idx, r))

        return rects

    def hit_test(self, xy: tuple[int, int]) -> bool:
        """Returns True if point is inside header OR any open option."""
        if self.rect.collidepoint(xy):
            return True
        return any(s.rect.collidepoint(xy) for s in self._menu_sprites)
