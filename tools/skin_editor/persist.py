"""Write edited documents back to source files.

* Skins: full module emission through the shared serializer
  (``instrument_cluster.ui.skins.serialize``, ``scale=None`` = verbatim),
  preserving the module's existing docstring.
* Palette / icons: surgical line rewrites — only each member's value
  changes, every comment and docstring in ``colors.py`` / ``icons.py``
  survives byte-for-byte. Glyphs are always written as ``\\uXXXX`` escapes.

All writes are atomic (same-directory temp + ``os.replace``).
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import instrument_cluster
from instrument_cluster.ui.colors import Color
from instrument_cluster.ui.icons import Icon
from instrument_cluster.ui.skins.serialize import emit_skin_module

PKG = Path(instrument_cluster.__file__).parent
SKINS_DIR = PKG / "ui" / "skins"
COLORS_PY = PKG / "ui" / "colors.py"
ICONS_PY = PKG / "ui" / "icons.py"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def skin_path(skin) -> Path:
    """Where a skin's module lives.

    A resolution can carry more than one skin — the panel default plus
    car-specific ones (Skin.car_id) — so the car has to be part of the
    filename. Without it, saving a car skin would silently overwrite the
    base skin for that panel, which is the same file every other skin of
    that resolution maps to.
    """
    stem = f"skin_{skin.width}x{skin.height}"
    if skin.car_id is not None:
        stem += f"_car{skin.car_id}"
    return SKINS_DIR / f"{stem}.py"


def _existing_docstring(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        doc = ast.get_docstring(ast.parse(path.read_text()))
        return (doc + "\n") if doc else ""
    except SyntaxError:
        return ""


def save_skin(doc) -> Path:
    """Emit the working skin over its module, keeping the docstring."""
    path = skin_path(doc.skin)
    text = emit_skin_module(doc.skin, docstring=_existing_docstring(path))
    _atomic_write(path, text)
    doc.mark_saved()
    return path


def save_palette(doc) -> Path:
    """Rewrite each Color member's rgb tuple in place."""
    text = COLORS_PY.read_text()
    for color in Color:
        rgb = doc.values[color]
        pattern = re.compile(
            r"^(    %s = \(auto\(\), )\([^)]*\)(\))" % re.escape(color.name),
            re.MULTILINE,
        )
        replacement = r"\g<1>%r\g<2>" % (tuple(rgb),)
        text, count = pattern.subn(replacement, text, count=1)
        if count != 1:
            raise RuntimeError(
                f"colors.py: member line for {color.name} not found — "
                "file layout changed; not saving"
            )
    _atomic_write(COLORS_PY, text)
    doc.mark_saved()
    return COLORS_PY


def save_icons(doc) -> Path:
    """Rewrite each Icon member's glyph escape in place."""
    text = ICONS_PY.read_text()
    for icon in Icon:
        glyph = doc.values[icon]
        escape = "".join(f"\\u{ord(ch):04x}" for ch in glyph)
        pattern = re.compile(
            r'^(    %s = ")(?:\\u[0-9a-fA-F]{4})+(")' % re.escape(icon.name),
            re.MULTILINE,
        )
        text, count = pattern.subn(
            lambda m: m.group(1) + escape + m.group(2), text, count=1
        )
        if count != 1:
            raise RuntimeError(
                f"icons.py: member line for {icon.name} not found — "
                "file layout changed; not saving"
            )
    _atomic_write(ICONS_PY, text)
    doc.mark_saved()
    return ICONS_PY
