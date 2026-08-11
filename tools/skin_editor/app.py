"""EditorApp: window, layout, event routing, and the edit→rebuild loop."""

from __future__ import annotations

import pygame

from instrument_cluster.ui.skins import SKIN_800, SKIN_1024, SKIN_1280

from . import paths, persist, uikit, viewhost as viewhost_mod
from .bindings import bindings_for
from .canvas import Canvas
from .document import IconsDocument, PaletteDocument, SkinDocument, UndoStack
from .glyph_picker import GlyphPicker
from .panels import (
    LEFT_W,
    RIGHT_W,
    STATUS_H,
    TOOLBAR_H,
    PropertiesPanel,
    StatusBar,
    Toolbar,
    TreePanel,
)

REBUILD_THROTTLE_S = 0.03


class QuitPrompt:
    """Drawn modal shown when quitting with unsaved changes."""

    def __init__(self, screen_rect, on_save_quit, on_discard, on_cancel):
        self.rect = pygame.Rect(0, 0, 420, 150)
        self.rect.center = screen_rect.center
        bx, by = self.rect.x + 16, self.rect.bottom - 50
        self.buttons = [
            uikit.Button((bx, by, 130, 34), "Save & quit", on_save_quit),
            uikit.Button((bx + 140, by, 120, 34), "Discard", on_discard),
            uikit.Button((bx + 270, by, 120, 34), "Cancel", on_cancel),
        ]
        self._cancel = on_cancel

    def handle(self, event) -> bool:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._cancel()
            return True
        for b in self.buttons:
            if b.handle(event):
                return True
        return event.type != pygame.QUIT

    def draw(self, screen):
        scrim = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        scrim.fill((0, 0, 0, 160))
        screen.blit(scrim, (0, 0))
        pygame.draw.rect(screen, uikit.THEME["panel"], self.rect, border_radius=6)
        pygame.draw.rect(
            screen, uikit.THEME["panel_edge"], self.rect, 1, border_radius=6
        )
        uikit.text(
            screen,
            "Unsaved changes",
            (self.rect.x + 16, self.rect.y + 14),
            uikit.THEME["text"],
            uikit.font(17),
        )
        uikit.text(
            screen,
            "Save them to the source files before quitting?",
            (self.rect.x + 16, self.rect.y + 44),
            uikit.THEME["text_dim"],
        )
        for b in self.buttons:
            b.draw(screen)


class EditorApp:
    def __init__(self, *, skin: str | None = None, view: str | None = None):
        self.screen = pygame.display.set_mode((1600, 1000), pygame.RESIZABLE)
        pygame.display.set_caption("Revokyte Skin Editor")

        self.skin_docs = [
            SkinDocument(SKIN_1280),
            SkinDocument(SKIN_1024),
            SkinDocument(SKIN_800),
        ]
        self.skin_index = {"1280x720": 0, "1024x600": 1, "800x480": 2}.get(skin, 0)
        self.palette_doc = PaletteDocument()
        self.icons_doc = IconsDocument()
        self.undo = UndoStack()

        self.mode = "layout"  # layout | palette | icons
        self.selected_path: str | None = None
        self.selected_color = None
        self.selected_icon = None
        self.modal: GlyphPicker | None = None

        self.viewhost = viewhost_mod.ViewHost()
        if view:
            self.viewhost.view_id = view

        self._needs_render = True
        self._render_cooldown = 0.0
        # Transient status-bar feedback ("Saved …", "Undid …").
        self._flash: tuple[str, int] = ("", 0)

        self._build_layout()
        self.canvas.bindings = bindings_for(self.viewhost.view_id)

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def _build_layout(self):
        w, h = self.screen.get_size()
        body_y = TOOLBAR_H + 4
        body_h = h - body_y - STATUS_H - 4
        self.toolbar = Toolbar(self)
        self.tree_panel = TreePanel(self, (4, body_y, LEFT_W, body_h))
        self.props_panel = PropertiesPanel(
            self, (w - RIGHT_W - 4, body_y, RIGHT_W, body_h)
        )
        canvas_rect = (
            LEFT_W + 12,
            body_y,
            w - LEFT_W - RIGHT_W - 24,
            body_h,
        )
        prev = getattr(self, "canvas", None)
        self.canvas = Canvas(
            canvas_rect,
            on_edit=self._live_edit,
            on_select=self._canvas_selected,
            on_gesture_end=self._gesture_end,
        )
        if prev is not None:
            self.canvas.bindings = prev.bindings
            self.canvas.selected = prev.selected
            self.canvas.zoom_full = prev.zoom_full
        self.status_bar = StatusBar(self)
        self.props_panel.rebuild()

    # ------------------------------------------------------------------
    # state helpers
    # ------------------------------------------------------------------
    @property
    def skin_doc(self) -> SkinDocument:
        return self.skin_docs[self.skin_index]

    @property
    def any_dirty(self) -> bool:
        return (
            any(d.dirty for d in self.skin_docs)
            or self.palette_doc.dirty
            or self.icons_doc.dirty
        )

    def axis_of(self, path: str) -> str:
        return paths.axis_at(self.skin_doc.skin, path)

    def request_render(self):
        self._needs_render = True

    def flash(self, message: str) -> None:
        self._flash = (message, pygame.time.get_ticks())

    def flash_text(self) -> str:
        message, born = self._flash
        if message and pygame.time.get_ticks() - born < 3000:
            return message
        return ""

    # ------------------------------------------------------------------
    # actions (toolbar / tree / canvas callbacks)
    # ------------------------------------------------------------------
    def select_skin(self, index: int):
        self.skin_index = index
        self.selected_path = None
        self.canvas.selected = None
        self.tree_panel.refresh()
        self.props_panel.rebuild()
        self.request_render()

    def select_view(self, view_id: str):
        self.viewhost.view_id = view_id
        self.canvas.bindings = bindings_for(view_id)
        self.canvas.selected = None
        self.selected_path = None
        self.tree_panel.view_list.selected_key = view_id
        self.tree_panel.tree.selected_key = None
        self.tree_panel.refresh()  # the tree is scoped to the view
        self.props_panel.rebuild()
        self.request_render()

    def set_mode(self, mode: str):
        self.mode = mode
        self.tree_panel.refresh()
        self.props_panel.rebuild()

    def toggle_zoom(self):
        self.canvas.zoom_full = not self.canvas.zoom_full

    def select_path(self, key, from_tree: bool = False):
        if self.mode == "palette":
            self.selected_color = key
            self.props_panel.rebuild()
            return
        if self.mode == "icons":
            self.selected_icon = key
            self.props_panel.rebuild()
            return
        self.selected_path = key
        if from_tree:
            match = next(
                (b for b in self.canvas.bindings if b.path == key), None
            )
            self.canvas.selected = match
        self.props_panel.rebuild()

    def _canvas_selected(self, binding):
        self.selected_path = binding.path if binding else None
        if binding:
            self.tree_panel.tree.selected_key = binding.path
            self.tree_panel.tree.scroll_to_key(binding.path)
        self.props_panel.rebuild()

    # -- edits ----------------------------------------------------------
    def _live_edit(self, path: str, value):
        self.skin_doc.set(path, value)
        self.request_render()

    def _gesture_end(self, path: str, old):
        new = self.skin_doc.get(path)
        self.undo.push(self.skin_doc, path, old, new)

    def edit_scalar(self, path: str, delta: int):
        old = self.skin_doc.get(path)
        self.skin_doc.set(path, old + delta)
        self.undo.push(self.skin_doc, path, old, self.skin_doc.get(path))
        self.request_render()

    def edit_family(self, path: str, delta: int):
        """Cycle a font-family field through the FontFamily members."""
        from instrument_cluster.ui.utils import FontFamily

        names = list(FontFamily.__members__)
        old = self.skin_doc.get(path)
        index = (names.index(old) + delta) % len(names)
        self.skin_doc.set(path, names[index])
        self.undo.push(self.skin_doc, path, old, self.skin_doc.get(path))
        self.props_panel.rebuild()
        self.request_render()

    def edit_component(self, path: str, index: int, delta: int):
        old = self.skin_doc.get(path)
        value = list(old)
        value[index] += delta
        self.skin_doc.set(path, tuple(value))
        self.undo.push(self.skin_doc, path, old, self.skin_doc.get(path))
        self.request_render()

    def edit_palette_channel(self, channel: int, delta: int):
        color = self.selected_color
        old = self.palette_doc.get(color)
        rgb = list(old)
        rgb[channel] += delta
        self.palette_doc.set(color, tuple(rgb))
        self.undo.push(self.palette_doc, color, old, self.palette_doc.get(color))
        self.props_panel.rebuild()
        self.request_render()

    def open_glyph_picker(self):
        icon = self.selected_icon
        if icon is None:
            return

        def pick(glyph):
            old = self.icons_doc.get(icon)
            self.icons_doc.set(icon, glyph)
            self.undo.push(self.icons_doc, icon, old, glyph)
            self.props_panel.rebuild()
            self.request_render()

        self.modal = GlyphPicker(
            self.screen.get_rect(), pick, self._close_modal
        )

    def _close_modal(self):
        self.modal = None

    def _request_quit(self):
        if not self.any_dirty:
            self._running = False
            return

        def save_quit():
            self.save_all()
            self._running = False

        def discard():
            self._running = False

        self.modal = QuitPrompt(
            self.screen.get_rect(), save_quit, discard, self._close_modal
        )

    def undo_once(self):
        entry = self.undo.undo()
        if entry:
            self._after_history(entry[0])
            self.flash(f"Undid {self._describe_key(entry[1])}")

    def redo_once(self):
        entry = self.undo.redo()
        if entry:
            self._after_history(entry[0])
            self.flash(f"Redid {self._describe_key(entry[1])}")

    @staticmethod
    def _describe_key(key) -> str:
        # Skin paths are strings; palette/icon keys are enum members.
        return getattr(key, "name", key)

    def _after_history(self, doc):
        if isinstance(doc, SkinDocument):
            self.skin_index = self.skin_docs.index(doc)
        self.tree_panel.refresh()
        self.props_panel.rebuild()
        self.request_render()

    def save_all(self):
        saved = []
        for doc in self.skin_docs:
            if doc.dirty:
                saved.append(persist.save_skin(doc).name)
        if self.palette_doc.dirty:
            saved.append(persist.save_palette(self.palette_doc).name)
        if self.icons_doc.dirty:
            saved.append(persist.save_icons(self.icons_doc).name)
        if saved:
            self.flash("Saved " + ", ".join(saved))

    # ------------------------------------------------------------------
    # main loop
    # ------------------------------------------------------------------
    def run(self):
        clock = pygame.time.Clock()
        self._running = True
        while self._running:
            dt = clock.tick(60) / 1000

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._request_quit()
                elif event.type == pygame.VIDEORESIZE:
                    self._build_layout()
                elif self.modal is not None:
                    self.modal.handle(event)
                elif event.type == pygame.KEYDOWN:
                    self._key(event)
                else:
                    if self.toolbar.handle(event):
                        continue
                    if self.tree_panel.handle(event):
                        continue
                    if self.props_panel.handle(event):
                        continue
                    if self.mode == "layout":
                        self.canvas.handle(
                            event, self.skin_doc.skin, self.skin_doc.get
                        )

            self.props_panel.update(dt)

            self._render_cooldown = max(0.0, self._render_cooldown - dt)
            if self._needs_render and self._render_cooldown == 0.0:
                self._needs_render = False
                self._render_cooldown = REBUILD_THROTTLE_S
                self.canvas.set_surface(
                    self.viewhost.render(self.skin_doc.skin)
                )

            self._draw()
            pygame.display.flip()

    def _key(self, event):
        mods = pygame.key.get_mods()
        ctrl = mods & (pygame.KMOD_CTRL | pygame.KMOD_META)
        shift = mods & pygame.KMOD_SHIFT
        if ctrl and event.key == pygame.K_s:
            self.save_all()
        elif ctrl and event.key == pygame.K_z and shift:
            self.redo_once()
        elif ctrl and event.key == pygame.K_z:
            self.undo_once()
        elif ctrl and event.key == pygame.K_y:
            self.redo_once()
        elif event.key == pygame.K_ESCAPE:
            self.canvas.selected = None
            self.selected_path = None
            self.props_panel.rebuild()
        elif event.key in (
            pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN
        ) and self.mode == "layout":
            step = 10 if shift else 1
            dx = {pygame.K_LEFT: -step, pygame.K_RIGHT: step}.get(event.key, 0)
            dy = {pygame.K_UP: -step, pygame.K_DOWN: step}.get(event.key, 0)
            if self.canvas.nudge(self.skin_doc.skin, dx, dy, self.skin_doc.get):
                self.props_panel.rebuild()
                self.request_render()

    def _draw(self):
        self.screen.fill(uikit.THEME["bg"])
        if self.mode == "layout":
            self.canvas.draw(
                self.screen, self.skin_doc.skin, self.viewhost.error
            )
        else:
            self.canvas.draw(self.screen, self.skin_doc.skin, self.viewhost.error)
        self.toolbar.draw(self.screen)
        self.tree_panel.draw(self.screen)
        self.props_panel.draw(self.screen)
        self.status_bar.draw(self.screen)
        if self.modal is not None:
            self.modal.draw(self.screen)
