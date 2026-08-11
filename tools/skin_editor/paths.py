"""Dotted-path access into the frozen Skin dataclass tree.

The schema's axis metadata (``instrument_cluster.ui.skins.schema``) drives
everything generically: ``walk`` enumerates every editable field with its
axis, ``replace_at`` rebuilds the frozen tree for an edit, and ``clamp``
applies the same validity rules the skin tests enforce (ints, on-screen
bounds, font floors) so a saved skin can never fail the suite.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from typing import Any, Iterator

from instrument_cluster.ui.skins.schema import Skin, axis_of, iter_px_fields


def walk(obj, prefix: str = "") -> Iterator[tuple[str, str, Any]]:
    """Yield (dotted_path, axis, value) for every leaf field."""
    for f, value in iter_px_fields(obj):
        path = f"{prefix}.{f.name}" if prefix else f.name
        if is_dataclass(value):
            yield from walk(value, path)
        else:
            yield path, axis_of(f), value


def axis_at(skin: Skin, path: str) -> str:
    obj = skin
    parts = path.split(".")
    for name in parts[:-1]:
        obj = getattr(obj, name)
    for f in fields(obj):
        if f.name == parts[-1]:
            return axis_of(f)
    raise KeyError(path)


def get_at(skin: Skin, path: str) -> Any:
    obj = skin
    for name in path.split("."):
        obj = getattr(obj, name)
    return obj


def replace_at(skin: Skin, path: str, value: Any) -> Skin:
    """A new Skin with the leaf at ``path`` replaced (ancestors rebuilt)."""
    parts = path.split(".")

    def rebuild(obj, idx: int):
        name = parts[idx]
        if idx == len(parts) - 1:
            return replace(obj, **{name: value})
        child = rebuild(getattr(obj, name), idx + 1)
        return replace(obj, **{name: child})

    return rebuild(skin, 0)


def clamp(skin: Skin, path: str, axis: str, value: Any) -> Any:
    """Clamp an edit to the rules the skin test suite enforces."""
    w, h = skin.size

    def ci(v, lo, hi):
        return max(lo, min(hi, int(round(v))))

    if axis == "rect":
        x, y, rw, rh = value
        return (ci(x, 0, w), ci(y, 0, h), ci(rw, 1, w), ci(rh, 1, h))
    if axis == "pos":
        x, y = value
        return (ci(x, 0, w), ci(y, 0, h))
    if axis == "size":
        sw, sh = value
        return (ci(sw, 1, w), ci(sh, 1, h))
    if axis == "font":
        return max(8, int(round(value / 2)) * 2)
    if axis == "font_pixel":
        return max(8, int(round(value / 2)) * 2)
    if axis == "x":
        return ci(value, -w, w)  # shifts may be relative; keep sign
    if axis == "y":
        return ci(value, -h, h)
    if axis == "u":
        return int(round(value))
    if axis == "family":
        from instrument_cluster.ui.utils import FontFamily

        if value not in FontFamily.__members__:
            raise ValueError(f"unknown font family {value!r}")
        return value
    if axis == "color":
        from instrument_cluster.ui.colors import Color

        if value not in Color.__members__:
            raise ValueError(f"unknown palette color {value!r}")
        return value
    return int(round(value)) if isinstance(value, (int, float)) else value


#: axis → number of scalar components (for the properties panel).
COMPONENTS = {
    "rect": ("x", "y", "w", "h"),
    "pos": ("x", "y"),
    "size": ("w", "h"),
}
