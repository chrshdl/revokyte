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
    # Car-specific skins. Same resolution as their base skin; the registry
    # keys on (size, car_id) so they coexist.
    "SKIN_1280_CAR3588": ".skin_1280x720_car3588",
}

# Keyed by (logical size, car id). A resolution has one skin with car id
# None -- the panel default -- plus any number of car-specific ones.
_registry: dict[tuple[tuple[int, int], int | None], Skin] | None = None

# The car the dashboard is currently dressed for. Process state rather than a
# parameter because active_skin() is called from every widget constructor;
# adding an argument there would mean threading the car id through the whole
# view and plugin tree for a value that only ever changes between rebuilds.
_active_car: int | None = None


def __getattr__(name: str):
    if name in _SKIN_MODULES:
        return getattr(import_module(_SKIN_MODULES[name], __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _ensure_registry() -> None:
    global _registry
    if _registry is None:
        skins = [__getattr__(name) for name in _SKIN_MODULES]
        _registry = {(tuple(s.size), s.car_id): s for s in skins}


def active_skin() -> Skin:
    """The skin for the active panel and the currently selected car.

    Falls back to the panel's default skin (car id None) when the car has
    no hand-tuned skin, which is the case for every car but a handful.
    """
    from ...peripherals.display import active_profile

    _ensure_registry()
    size = tuple(active_profile().logical_size)
    skin = _registry.get((size, _active_car))
    if skin is None:
        skin = _registry.get((size, None))
    return skin if skin is not None else __getattr__("SKIN_1280")


def active_car() -> int | None:
    """The car id the dashboard is currently dressed for."""
    return _active_car


def has_skin_for_car(car_id: int | None) -> bool:
    """True when some panel carries a skin hand-tuned for ``car_id``."""
    if car_id is None:
        return False
    _ensure_registry()
    return any(car == car_id for _size, car in _registry)


def set_active_car(car_id: int | None) -> bool:
    """Select the car skin. Returns True when the resolved skin changed.

    The caller owns the (expensive) rebuild, so this reports whether one is
    actually needed rather than doing it: switching between two cars that
    both fall back to the panel default must not cost a rebuild.
    """
    global _active_car
    if car_id == _active_car:
        return False
    before = active_skin()
    _active_car = car_id
    return active_skin() is not before


def set_skin_override(skin: Skin) -> None:
    """Tooling only: register ``skin`` for its resolution in this process.

    The skin editor's live preview replaces the working skin after every
    edit and rebuilds the views; the app itself never calls this —
    persisted skin changes are rewrites of the ``skin_*.py`` modules.
    """
    _ensure_registry()
    _registry[(tuple(skin.size), skin.car_id)] = skin


def reset_skin_overrides() -> None:
    """Tooling only: drop overrides; next access reloads the modules."""
    global _registry, _active_car
    _registry = None
    _active_car = None


__all__ = [
    "Skin",
    "SKIN_1280",
    "SKIN_1024",
    "SKIN_800",
    "active_skin",
    "set_skin_override",
    "reset_skin_overrides",
]
