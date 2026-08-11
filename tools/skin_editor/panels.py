"""Editor panels: toolbar, left tree, right properties, status bar.

The layout follows EB GUIDE Studio's arrangement — project/view tree on the
left, WYSIWYG scene in the center, properties of the selection on the
right — all drawn regions inside one pygame window.
"""

from __future__ import annotations

import pygame

from instrument_cluster.ui.colors import Color
from instrument_cluster.ui.icons import Icon
from instrument_cluster.ui.utils import FontFamily, load_font_px

from . import uikit, view_tree, viewhost
from .paths import COMPONENTS, axis_at

TOOLBAR_H = 44
STATUS_H = 26
LEFT_W = 290
RIGHT_W = 310


class Toolbar:
    def __init__(self, app):
        self.app = app
        self.buttons: list[uikit.Button] = []
        self._build()

    def _build(self):
        a = self.app
        self.buttons = []
        x = 8
        for i, doc in enumerate(a.skin_docs):
            label = doc.label
            self.buttons.append(
                uikit.Button(
                    (x, 8, 110, TOOLBAR_H - 16),
                    label,
                    lambda i=i: a.select_skin(i),
                    toggle_state=lambda i=i: a.skin_index == i,
                )
            )
            x += 116
        x += 16
        for mode, label in (("layout", "Layout"), ("palette", "Palette"), ("icons", "Icons")):
            self.buttons.append(
                uikit.Button(
                    (x, 8, 86, TOOLBAR_H - 16),
                    label,
                    lambda m=mode: a.set_mode(m),
                    toggle_state=lambda m=mode: a.mode == m,
                )
            )
            x += 92
        x += 16
        self.buttons.append(
            uikit.Button(
                (x, 8, 104, TOOLBAR_H - 16),
                lambda: "Save •" if a.any_dirty else "Save",
                a.save_all,
                enabled=lambda: a.any_dirty,
                accent=True,
                icon=uikit.ICON_SAVE,
            )
        )
        x += 110
        self.buttons.append(
            uikit.Button((x, 8, 90, TOOLBAR_H - 16), "Undo", a.undo_once,
                         enabled=lambda: a.undo.can_undo,
                         icon=uikit.ICON_UNDO)
        )
        x += 96
        self.buttons.append(
            uikit.Button((x, 8, 90, TOOLBAR_H - 16), "Redo", a.redo_once,
                         enabled=lambda: a.undo.can_redo,
                         icon=uikit.ICON_REDO)
        )
        x += 96
        self.buttons.append(
            uikit.Button(
                (x, 8, 84, TOOLBAR_H - 16),
                "100% / Fit",
                a.toggle_zoom,
                toggle_state=lambda: a.canvas.zoom_full,
            )
        )

    def handle(self, event) -> bool:
        return any(b.handle(event) for b in self.buttons)

    def draw(self, screen):
        pygame.draw.rect(
            screen, uikit.THEME["panel"], (0, 0, screen.get_width(), TOOLBAR_H)
        )
        pygame.draw.line(
            screen,
            uikit.THEME["panel_edge"],
            (0, TOOLBAR_H - 1),
            (screen.get_width(), TOOLBAR_H - 1),
        )
        for b in self.buttons:
            b.draw(screen)
        # dirty markers on skin tabs
        for i, doc in enumerate(self.app.skin_docs):
            if doc.dirty:
                bx = 8 + i * 116 + 100
                pygame.draw.circle(screen, uikit.THEME["dirty"], (bx, 16), 4)


class TreePanel:
    """View selector on top, the skin field tree below (layout mode); the
    palette / icon lists in their modes."""

    def __init__(self, app, rect):
        self.app = app
        self.rect = pygame.Rect(rect)
        #: expanded widget sections, per EB-GUIDE-style collapsible tree.
        self.expanded: set[str] = set()
        rect = self.rect
        view_h = len(viewhost.VIEWS) * uikit.ScrollList.ROW_H + 6
        self.view_list = uikit.ScrollList(
            (rect.x, rect.y + 24, rect.width, view_h), self._pick_view
        )
        self.view_list.set_rows(
            [(vid, label, 0, "leaf") for vid, label in viewhost.VIEWS]
        )
        self.view_list.selected_key = app.viewhost.view_id
        tree_y = self.view_list.rect.bottom + 26
        self.tree = uikit.ScrollList(
            (rect.x, tree_y, rect.width, rect.bottom - tree_y), self._pick_field
        )
        self.refresh()

    def _pick_view(self, view_id):
        self.app.select_view(view_id)

    def _pick_field(self, key):
        if isinstance(key, str) and key.startswith("#"):
            # A widget section: toggle its fields open and inspect it.
            name = key[1:]
            if name in self.expanded:
                self.expanded.discard(name)
            else:
                self.expanded.add(name)
            self.refresh()
            self.app.select_section(name)
        else:
            self.app.select_path(key, from_tree=True)

    def reveal(self, section: str, path: str | None) -> None:
        """Expand ``section`` and highlight ``path`` (canvas selection)."""
        self.expanded.add(section)
        self.refresh()
        self.tree.selected_key = path if path else f"#{section}"
        self.tree.scroll_to_key(self.tree.selected_key)

    def refresh(self):
        a = self.app
        # The view list only exists in layout mode; the palette/icon lists
        # take the whole panel.
        if a.mode == "layout":
            tree_y = self.view_list.rect.bottom + 26
        else:
            tree_y = self.rect.y + 24
        self.tree.rect.update(
            self.rect.x, tree_y, self.rect.width, self.rect.bottom - tree_y
        )
        if a.mode == "layout":
            # The widget tree of the *selected view*: sections are the
            # view's widgets (collapsible), leaves the skin fields that
            # style them. Clicking a widget shows all its properties in
            # the inspector.
            rows = []
            skin = a.skin_doc.skin
            for section, field_paths in view_tree.tree_for(a.viewhost.view_id):
                marker = "−" if section in self.expanded else "+"
                rows.append((f"#{section}", f"{marker}  {section}", 0, "group"))
                if section not in self.expanded:
                    continue
                for path in field_paths:
                    leaf = path.rsplit(".", 1)[-1]
                    axis = axis_at(skin, path)
                    rows.append((path, f"{leaf}  ({axis})", 1, "leaf"))
            self.tree.set_rows(rows)
        elif a.mode == "palette":
            self.tree.set_rows(
                [(c, c.name, 0, "leaf") for c in Color]
            )
        else:  # icons
            self.tree.set_rows(
                [(i, i.name, 0, "leaf") for i in Icon]
            )

    def handle(self, event) -> bool:
        if self.app.mode == "layout" and self.view_list.handle(event):
            return True
        return self.tree.handle(event)

    def draw(self, screen):
        uikit.panel(screen, self.rect)
        if self.app.mode == "layout":
            uikit.text(
                screen, "VIEWS", (self.rect.x + 10, self.rect.y + 5),
                uikit.THEME["text_dim"], uikit.small_font(),
            )
            self.view_list.draw(screen)
            label = dict(viewhost.VIEWS).get(self.app.viewhost.view_id, "")
            uikit.text(
                screen, f"WIDGETS — {label.upper()}",
                (self.rect.x + 10, self.view_list.rect.bottom + 7),
                uikit.THEME["text_dim"], uikit.small_font(),
            )
        else:
            title = "PALETTE" if self.app.mode == "palette" else "ICONS"
            uikit.text(
                screen, title, (self.rect.x + 10, self.rect.y + 5),
                uikit.THEME["text_dim"], uikit.small_font(),
            )
        self.tree.draw(screen)
        if self.app.mode == "palette":
            self._swatches(screen)
        elif self.app.mode == "icons":
            self._glyph_cells(screen)

    def _swatches(self, screen):
        lst = self.tree
        first = lst.offset // lst.ROW_H
        last = min(len(lst.rows), first + lst.rect.height // lst.ROW_H + 2)
        prev = screen.get_clip()
        screen.set_clip(lst.rect)
        for i in range(first, last):
            color = lst.rows[i][0]
            y = lst.rect.y + i * lst.ROW_H - lst.offset
            rgb = self.app.palette_doc.get(color)
            r = pygame.Rect(lst.rect.right - 44, y + 4, 30, lst.ROW_H - 8)
            pygame.draw.rect(screen, rgb, r)
            pygame.draw.rect(screen, uikit.THEME["panel_edge"], r, 1)
        screen.set_clip(prev)

    def _glyph_cells(self, screen):
        lst = self.tree
        icon_font = load_font_px(18, FontFamily.MATERIAL_SYMBOLS)
        first = lst.offset // lst.ROW_H
        last = min(len(lst.rows), first + lst.rect.height // lst.ROW_H + 2)
        prev = screen.get_clip()
        screen.set_clip(lst.rect)
        for i in range(first, last):
            icon = lst.rows[i][0]
            y = lst.rect.y + i * lst.ROW_H - lst.offset
            glyph = self.app.icons_doc.get(icon)
            surf = icon_font.render(glyph, True, uikit.THEME["text"])
            screen.blit(surf, (lst.rect.right - 36, y + 2))
        screen.set_clip(prev)


class PropertiesPanel:
    """The inspector (right side).

    Layout mode shows the *selected widget's* full property sheet — every
    field of the tree section (rect, fonts, families, colors) as stacked
    editors, scrollable when it outgrows the panel, with the field picked
    on the canvas highlighted. Palette / Icons modes keep their focused
    single-selection editors.
    """

    FIELDS_TOP = 56  # fixed header band (title + subtitle)

    def __init__(self, app, rect):
        self.app = app
        self.rect = pygame.Rect(rect)
        self.steppers: list[uikit.Stepper] = []
        self.buttons: list[uikit.Button] = []
        #: per-field metadata: dicts with path/axis/label_y/block/steppers/button
        self._editors: list[dict] = []
        self.scroll = 0
        self._content_h = 0
        self._title = ""
        self._subtitle = ""

    # -- lookup ----------------------------------------------------------
    def steppers_for(self, path: str) -> list:
        for ed in self._editors:
            if ed["path"] == path:
                return ed["steppers"]
        return []

    def button_for(self, path: str):
        for ed in self._editors:
            if ed["path"] == path:
                return ed["button"]
        return None

    def _viewport(self) -> pygame.Rect:
        return pygame.Rect(
            self.rect.x,
            self.rect.y + self.FIELDS_TOP,
            self.rect.width,
            self.rect.height - self.FIELDS_TOP,
        )

    # -- building -------------------------------------------------------
    def rebuild(self):
        a = self.app
        self.steppers, self.buttons, self._editors = [], [], []
        x = self.rect.x + 14
        w = self.rect.width - 28
        y = self.rect.y + 74

        if a.mode == "palette" and a.selected_color is not None:
            color = a.selected_color
            self._title = color.name
            self._subtitle = "#%02x%02x%02x" % tuple(a.palette_doc.get(color)[:3])
            for i, ch in enumerate("RGB"):
                self.steppers.append(
                    uikit.Stepper(
                        (x, y + 20 + i * 56, w, 30),
                        ch,
                        lambda i=i: a.palette_doc.get(color)[i],
                        lambda d, i=i: a.edit_palette_channel(i, d),
                        step=1,
                    )
                )
            return

        if a.mode == "icons" and a.selected_icon is not None:
            icon = a.selected_icon
            self._title = icon.name
            self._subtitle = "U+%04X" % ord(a.icons_doc.get(icon))
            self.buttons.append(
                uikit.Button(
                    (x, y + 150, w, 34), "Choose glyph…", a.open_glyph_picker
                )
            )
            return

        fields = a.section_fields()
        if not fields:
            self._title, self._subtitle = "", ""
            return
        self._title = a.selected_section or ""
        self._subtitle = f"{len(fields)} properties"

        skin = a.skin_doc.skin
        cursor = self.rect.y + self.FIELDS_TOP + 8 - self.scroll
        for path in fields:
            axis = a.axis_of(path)
            value = a.skin_doc.get(path)
            block_top = cursor
            label_y = cursor
            cursor += 20
            steppers, button = [], None
            step = 8 if axis == "font_pixel" else 2 if axis == "font" else 1

            if axis == "color":
                steppers.append(
                    uikit.Stepper(
                        (x, cursor, w, 30),
                        None,
                        lambda p=path: a.skin_doc.get(p),
                        lambda d, p=path: a.edit_color(p, d),
                        step=1,
                    )
                )
                cursor += 36
                button = uikit.Button(
                    (x, cursor, w, 26),
                    "Choose color…",
                    lambda p=path: a.open_color_picker(p),
                )
                cursor += 32
            elif axis == "family":
                steppers.append(
                    uikit.Stepper(
                        (x, cursor, w, 30),
                        None,
                        lambda p=path: a.skin_doc.get(p),
                        lambda d, p=path: a.edit_family(p, d),
                        step=1,
                    )
                )
                cursor += 36
            elif isinstance(value, tuple):
                names = COMPONENTS.get(
                    axis, tuple(f"[{i}]" for i in range(len(value)))
                )
                for i, name in enumerate(names):
                    steppers.append(
                        uikit.Stepper(
                            (x + 24, cursor, w - 24, 30),
                            None,
                            lambda p=path, i=i: a.skin_doc.get(p)[i],
                            lambda d, p=path, i=i: a.edit_component(p, i, d),
                            step=step,
                        )
                    )
                    steppers[-1].prefix = name  # drawn left of the row
                    cursor += 36
            else:
                steppers.append(
                    uikit.Stepper(
                        (x, cursor, w, 30),
                        None,
                        lambda p=path: a.skin_doc.get(p),
                        lambda d, p=path: a.edit_scalar(p, d),
                        step=step,
                    )
                )
                cursor += 36

            cursor += 10
            self.steppers.extend(steppers)
            if button is not None:
                self.buttons.append(button)
            self._editors.append(
                {
                    "path": path,
                    "axis": axis,
                    "label_y": label_y,
                    "block": pygame.Rect(
                        self.rect.x + 4, block_top - 4, self.rect.width - 8,
                        cursor - block_top,
                    ),
                    "steppers": steppers,
                    "button": button,
                }
            )

        self._content_h = (cursor + self.scroll) - (
            self.rect.y + self.FIELDS_TOP + 8
        )

    # -- events / drawing ----------------------------------------------
    @property
    def max_scroll(self) -> int:
        viewport_h = self.rect.height - self.FIELDS_TOP - 8
        return max(0, self._content_h - viewport_h)

    def handle(self, event) -> bool:
        viewport = self._viewport()
        in_layout = self.app.mode == "layout"
        for s in self.steppers:
            if in_layout and not viewport.colliderect(s.rect):
                continue  # scrolled out of view: no ghost hits
            if s.handle(event):
                return True
        for b in self.buttons:
            if in_layout and not viewport.colliderect(b.rect):
                continue
            if b.handle(event):
                return True
        if (
            in_layout
            and event.type == pygame.MOUSEWHEEL
            and self.rect.collidepoint(pygame.mouse.get_pos())
            and self.max_scroll
        ):
            self.scroll = max(0, min(self.max_scroll, self.scroll - event.y * 40))
            self.rebuild()
            return True
        return False

    def handle_key(self, event) -> bool:
        """Route a KEYDOWN to an inline value entry, if one is open —
        called by the app *before* its own shortcuts, so typing "44" or
        pressing Esc edits the value instead of nudging/deselecting."""
        return any(s.handle_key(event) for s in self.steppers if s.editing)

    def update(self, dt):
        for s in self.steppers:
            s.update(dt)

    def draw(self, screen):
        uikit.panel(screen, self.rect, "PROPERTIES")
        a = self.app
        if not self._title:
            uikit.text(
                screen,
                "Click a widget in the tree",
                (self.rect.x + 14, self.rect.y + 40),
                uikit.THEME["text_dim"],
            )
            uikit.text(
                screen,
                "or an element on the canvas.",
                (self.rect.x + 14, self.rect.y + 62),
                uikit.THEME["text_dim"],
            )
            return

        if a.mode != "layout":
            self._draw_focused(screen)
            return

        # Fixed header band.
        uikit.text(screen, self._title, (self.rect.x + 14, self.rect.y + 24), uikit.THEME["text"], uikit.font(17))
        uikit.text(screen, self._subtitle, (self.rect.x + 14, self.rect.y + 46), uikit.THEME["text_dim"], uikit.small_font())

        viewport = self._viewport()
        prev_clip = screen.get_clip()
        screen.set_clip(viewport)

        for ed in self._editors:
            if not viewport.colliderect(ed["block"]):
                continue
            if ed["path"] == a.selected_path:
                pygame.draw.rect(screen, uikit.THEME["row_selected"], ed["block"], border_radius=4)
            leaf = ed["path"].rsplit(".", 1)[-1]
            uikit.text(
                screen,
                f"{leaf}  ({ed['axis']})",
                (self.rect.x + 14, ed["label_y"]),
                uikit.THEME["text_dim"],
                uikit.small_font(),
            )
            if ed["axis"] == "color":
                rgb = Color[a.skin_doc.get(ed["path"])].rgb()
                sw = pygame.Rect(self.rect.right - 46, ed["label_y"], 30, 16)
                pygame.draw.rect(screen, rgb, sw)
                pygame.draw.rect(screen, uikit.THEME["panel_edge"], sw, 1)
            for s in ed["steppers"]:
                prefix = getattr(s, "prefix", None)
                if prefix:
                    uikit.text(
                        screen,
                        prefix,
                        (self.rect.x + 14, s.rect.y + 6),
                        uikit.THEME["text_dim"],
                        uikit.small_font(),
                    )
                s.draw(screen)
            if ed["button"] is not None:
                ed["button"].draw(screen)

        screen.set_clip(prev_clip)
        if self.max_scroll:
            frac = (self.rect.height - self.FIELDS_TOP) / self._content_h
            thumb_h = max(24, int((self.rect.height - self.FIELDS_TOP) * frac))
            thumb_y = viewport.y + int(
                (viewport.height - thumb_h) * (self.scroll / self.max_scroll)
            )
            pygame.draw.rect(
                screen,
                uikit.THEME["panel_edge"],
                (self.rect.right - 6, thumb_y, 4, thumb_h),
                border_radius=2,
            )

    def _draw_focused(self, screen):
        """Palette / Icons single-selection view (unchanged behavior)."""
        a = self.app
        uikit.text(screen, self._title, (self.rect.x + 14, self.rect.y + 26), uikit.THEME["text"], uikit.font(17))
        uikit.text(screen, self._subtitle, (self.rect.x + 14, self.rect.y + 50), uikit.THEME["text_dim"], uikit.small_font())
        for s in self.steppers:
            s.draw(screen)
        for b in self.buttons:
            b.draw(screen)
        if a.mode == "icons" and a.selected_icon is not None:
            glyph = a.icons_doc.get(a.selected_icon)
            big = load_font_px(96, FontFamily.MATERIAL_SYMBOLS)
            surf = big.render(glyph, True, uikit.THEME["text"])
            screen.blit(
                surf,
                surf.get_rect(midtop=(self.rect.centerx, self.rect.y + 92)),
            )
        if a.mode == "palette" and a.selected_color is not None:
            rgb = a.palette_doc.get(a.selected_color)
            r = pygame.Rect(self.rect.x + 14, self.rect.bottom - 90, self.rect.width - 28, 60)
            pygame.draw.rect(screen, rgb, r)
            pygame.draw.rect(screen, uikit.THEME["panel_edge"], r, 1)


class StatusBar:
    def __init__(self, app):
        self.app = app

    def draw(self, screen):
        a = self.app
        h = screen.get_height()
        rect = pygame.Rect(0, h - STATUS_H, screen.get_width(), STATUS_H)
        pygame.draw.rect(screen, uikit.THEME["panel"], rect)
        pygame.draw.line(
            screen, uikit.THEME["panel_edge"], rect.topleft, rect.topright
        )
        flash = a.flash_text()
        if flash:
            uikit.text(
                screen, flash, (10, h - STATUS_H + 4),
                uikit.THEME["accent"], uikit.small_font(),
            )
        parts = []
        if not flash and a.mode == "layout":
            if a.selected_path:
                axis = a.axis_of(a.selected_path)
                parts.append(f"{a.selected_path}  ({axis})  {a.skin_doc.get(a.selected_path)!r}")
                if a.canvas.selected is not None and a.canvas.selected.note:
                    parts.append(f"[{a.canvas.selected.note}]")
            else:
                parts.append("click a gauge on the canvas, or pick a field in the tree")
        elif not flash and a.mode == "palette":
            parts.append("palette edits apply to all skins; Save rewrites ui/colors.py")
        elif not flash:
            parts.append("icon edits apply to all skins; Save rewrites ui/icons.py")
        zoom = "100%" if a.canvas.zoom_full else f"fit {a.canvas.scale:.0%}"
        dirty = " ● unsaved" if a.any_dirty else ""
        uikit.text(
            screen, "   ".join(parts), (10, h - STATUS_H + 4), uikit.THEME["text_dim"], uikit.small_font()
        )
        uikit.text(
            screen,
            f"{zoom}{dirty}",
            (screen.get_width() - 10, h - STATUS_H + 4),
            uikit.THEME["dirty"] if a.any_dirty else uikit.THEME["text_dim"],
            uikit.small_font(),
            right=True,
        )
