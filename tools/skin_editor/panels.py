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
            uikit.Button((x, 8, 76, TOOLBAR_H - 16), "Save", a.save_all,
                         enabled=lambda: a.any_dirty)
        )
        x += 82
        self.buttons.append(
            uikit.Button((x, 8, 70, TOOLBAR_H - 16), "Undo", a.undo_once,
                         enabled=lambda: a.undo.can_undo)
        )
        x += 76
        self.buttons.append(
            uikit.Button((x, 8, 70, TOOLBAR_H - 16), "Redo", a.redo_once,
                         enabled=lambda: a.undo.can_redo)
        )
        x += 76
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

    def _pick_field(self, path):
        self.app.select_path(path, from_tree=True)

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
            # view's widgets, leaves the skin fields that style them.
            rows = []
            skin = a.skin_doc.skin
            for section, field_paths in view_tree.tree_for(a.viewhost.view_id):
                rows.append((f"#{section}", section, 0, "group"))
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
    """Axis-aware editors for the selection (right side)."""

    def __init__(self, app, rect):
        self.app = app
        self.rect = pygame.Rect(rect)
        self.steppers: list[uikit.Stepper] = []
        self.buttons: list[uikit.Button] = []
        self._title = ""
        self._subtitle = ""

    # -- building -------------------------------------------------------
    def rebuild(self):
        a = self.app
        self.steppers, self.buttons = [], []
        x = self.rect.x + 14
        w = self.rect.width - 28
        # Controls start below the title + dotted-path block draw() paints
        # at rect.y+26/+50. The rects placed here are BOTH the hit-targets
        # and the drawn positions — draw() must never shift them (a
        # draw-time offset once left every stepper hit-tested 40px above
        # where it was painted: single steppers dead, stacked ones hitting
        # their neighbour below).
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

        path = a.selected_path
        if path is None:
            self._title, self._subtitle = "", ""
            return
        axis = a.axis_of(path)
        self._title = path.rsplit(".", 1)[-1]
        self._subtitle = f"{path}   ({axis})"
        value = a.skin_doc.get(path)
        if axis == "family":
            # -/+ cycles through the FontFamily members; the middle cell
            # shows the current face name.
            self.steppers.append(
                uikit.Stepper(
                    (x, y + 20, w, 30),
                    "font family",
                    lambda: a.skin_doc.get(path),
                    lambda d: a.edit_family(path, d),
                    step=1,
                )
            )
            return
        step = 8 if axis == "font_pixel" else 2 if axis == "font" else 1
        if isinstance(value, tuple):
            names = COMPONENTS.get(axis, tuple(f"[{i}]" for i in range(len(value))))
            for i, name in enumerate(names):
                self.steppers.append(
                    uikit.Stepper(
                        (x, y + 20 + i * 56, w, 30),
                        name,
                        lambda i=i: a.skin_doc.get(path)[i],
                        lambda d, i=i: a.edit_component(path, i, d),
                        step=step,
                    )
                )
        else:
            self.steppers.append(
                uikit.Stepper(
                    (x, y + 20, w, 30),
                    "value",
                    lambda: a.skin_doc.get(path),
                    lambda d: a.edit_scalar(path, d),
                    step=step,
                )
            )

    # -- events / drawing ----------------------------------------------
    def handle(self, event) -> bool:
        for s in self.steppers:
            if s.handle(event):
                return True
        return any(b.handle(event) for b in self.buttons)

    def update(self, dt):
        for s in self.steppers:
            s.update(dt)

    def draw(self, screen):
        uikit.panel(screen, self.rect, "PROPERTIES")
        if not self._title:
            uikit.text(
                screen,
                "Select a field in the tree\nor an element on the canvas.",
                (self.rect.x + 14, self.rect.y + 40),
                uikit.THEME["text_dim"],
            )
            return
        uikit.text(screen, self._title, (self.rect.x + 14, self.rect.y + 26), uikit.THEME["text"], uikit.font(17))
        uikit.text(screen, self._subtitle, (self.rect.x + 14, self.rect.y + 50), uikit.THEME["text_dim"], uikit.small_font())
        for s in self.steppers:
            s.draw(screen)
        for b in self.buttons:
            b.draw(screen)
        a = self.app
        if (
            a.mode == "layout"
            and a.selected_path
            and a.axis_of(a.selected_path) == "family"
        ):
            family = FontFamily[a.skin_doc.get(a.selected_path)]
            sample = load_font_px(30, family).render(
                "AaBbGg 0123", True, uikit.THEME["text"]
            )
            self.rect and screen.blit(
                sample,
                sample.get_rect(midtop=(self.rect.centerx, self.rect.y + 150)),
            )
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
        parts = []
        if a.mode == "layout":
            if a.selected_path:
                axis = a.axis_of(a.selected_path)
                parts.append(f"{a.selected_path}  ({axis})  {a.skin_doc.get(a.selected_path)!r}")
                if a.canvas.selected is not None and a.canvas.selected.note:
                    parts.append(f"[{a.canvas.selected.note}]")
            else:
                parts.append("click a gauge on the canvas, or pick a field in the tree")
        elif a.mode == "palette":
            parts.append("palette edits apply to all skins; Save rewrites ui/colors.py")
        else:
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
