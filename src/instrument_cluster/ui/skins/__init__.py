"""Per-resolution skins and the process-wide accessor.

``active_skin()`` resolves the skin for the active display profile's
logical size, lazily and at call time — never at import time. Views are
imported before the ``Display`` is constructed (see ``main.py``), so any
module-level skin read would freeze the dev fallback; skinned code reads
the skin at construction time, the same discipline the old ``sx/sy``
helpers enforced. Tests and pre-Display code paths resolve to SKIN_1280
via the dev profile default.

Unknown panel resolutions fall back to SKIN_1280: ``_resolve_profile``
already maps unmatched panels to the Pi profile (1280x720 logical), so
this fallback only fires for hand-edited configs.

The skin modules themselves are imported lazily (PEP 562) rather than at
package import: ``tools/gen_skin_seed.py`` must be able to import the
schema and the 1280 skin to regenerate a seeded skin file even while that
file is stale or mid-write.
"""

from __future__ import annotations

from importlib import import_module

from .schema import Skin

_SKIN_MODULES = {
    "SKIN_1280": ".skin_1280x720",
    "SKIN_1024": ".skin_1024x600",
    "SKIN_800": ".skin_800x480",
}

_registry: dict[tuple[int, int], Skin] | None = None


def __getattr__(name: str):
    if name in _SKIN_MODULES:
        return getattr(import_module(_SKIN_MODULES[name], __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def active_skin() -> Skin:
    """The skin matching the active display profile's logical size."""
    from ...peripherals.display import active_profile

    global _registry
    if _registry is None:
        skins = [__getattr__(name) for name in _SKIN_MODULES]
        _registry = {skin.size: skin for skin in skins}

    size = tuple(active_profile().logical_size)
    return _registry.get(size, __getattr__("SKIN_1280"))


def set_skin_override(skin: Skin) -> None:
    """Tooling only: register ``skin`` for its resolution in this process.

    The skin editor's live preview replaces the working skin after every
    edit and rebuilds the views; the app itself never calls this —
    persisted skin changes are rewrites of the ``skin_*.py`` modules.
    """
    active_skin()  # ensure the registry exists
    _registry[tuple(skin.size)] = skin


def reset_skin_overrides() -> None:
    """Tooling only: drop overrides; next access reloads the modules."""
    global _registry
    _registry = None


__all__ = [
    "Skin",
    "SKIN_1280",
    "SKIN_1024",
    "SKIN_800",
    "active_skin",
    "set_skin_override",
    "reset_skin_overrides",
]
