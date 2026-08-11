"""Editable documents (skins, palette, icons) and the shared undo stack.

Documents hold working state and apply edits through the runtime override
hooks so the ViewHost's next rebuild shows them; ``persist.py`` writes them
back to source files on save. Undo entries are (document, key, old, new)
tuples — the stack is shared across documents so Ctrl+Z rewinds whatever
the designer touched last, regardless of panel.
"""

from __future__ import annotations

from typing import Any

from instrument_cluster.ui.colors import (
    Color,
    reset_palette_overrides,
    set_palette_override,
)
from instrument_cluster.ui.icons import Icon, set_icon_override
from instrument_cluster.ui.skins import Skin, set_skin_override

from . import paths


class SkinDocument:
    """One skin's working copy. Edits clamp per axis and register the new
    frozen Skin as the process-wide override, so rebuilt views render it."""

    def __init__(self, skin: Skin):
        self.skin = skin
        self.saved = skin

    @property
    def dirty(self) -> bool:
        return self.skin != self.saved

    @property
    def label(self) -> str:
        return self.skin.name

    def get(self, path: str) -> Any:
        return paths.get_at(self.skin, path)

    def set(self, path: str, value: Any) -> Any:
        """Apply an edit; returns the previous value (for undo)."""
        axis = paths.axis_at(self.skin, path)
        value = paths.clamp(self.skin, path, axis, value)
        old = paths.get_at(self.skin, path)
        if value == old:
            return old
        self.skin = paths.replace_at(self.skin, path, value)
        set_skin_override(self.skin)
        return old

    def mark_saved(self) -> None:
        self.saved = self.skin


class PaletteDocument:
    """The global Color palette's working copy (name → rgb)."""

    def __init__(self):
        self.saved = {c: c.value[1] for c in Color}
        self.values = dict(self.saved)

    @property
    def dirty(self) -> bool:
        return self.values != self.saved

    def get(self, color: Color) -> tuple:
        return self.values[color]

    def set(self, color: Color, rgb: tuple) -> tuple:
        rgb = tuple(max(0, min(255, int(c))) for c in rgb[:3])
        old = self.values[color]
        if rgb == old:
            return old
        self.values[color] = rgb
        set_palette_override(color, rgb)
        return old

    def mark_saved(self) -> None:
        self.saved = dict(self.values)

    def reset(self) -> None:
        self.values = dict(self.saved)
        reset_palette_overrides()
        for color, rgb in self.values.items():
            if rgb != color.value[1]:
                set_palette_override(color, rgb)


class IconsDocument:
    """The icon registry's working copy (Icon → glyph)."""

    def __init__(self):
        self.saved = {i: i.value for i in Icon}
        self.values = dict(self.saved)

    @property
    def dirty(self) -> bool:
        return self.values != self.saved

    def get(self, icon: Icon) -> str:
        return self.values[icon]

    def set(self, icon: Icon, glyph: str) -> str:
        old = self.values[icon]
        if glyph == old:
            return old
        self.values[icon] = glyph
        set_icon_override(icon, glyph)
        return old

    def mark_saved(self) -> None:
        self.saved = dict(self.values)


class UndoStack:
    """Linear undo/redo of (document, key, old, new) commands."""

    LIMIT = 500

    def __init__(self):
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []

    def push(self, doc, key, old, new) -> None:
        if old == new:
            return
        self._undo.append((doc, key, old, new))
        del self._undo[: -self.LIMIT]
        self._redo.clear()

    def undo(self) -> tuple | None:
        if not self._undo:
            return None
        doc, key, old, new = self._undo.pop()
        doc.set(key, old)
        self._redo.append((doc, key, old, new))
        return (doc, key, old)

    def redo(self) -> tuple | None:
        if not self._redo:
            return None
        doc, key, old, new = self._redo.pop()
        doc.set(key, new)
        self._undo.append((doc, key, old, new))
        return (doc, key, new)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)
