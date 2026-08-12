"""The icon registry — every material-symbols glyph the HMI uses.

One semantic name per use, glyph values as ``\\uXXXX`` escapes (never raw
PUA characters — diff-friendly, and the skin editor rewrites this file).
Icons are shared across skins: which glyph a control shows is semantic;
only its *size* is a per-skin value (``active_skin()``).

``Icon.glyph()`` consults a runtime override store first — tooling only
(the skin editor's live preview): a tool can swap a glyph and rebuild
views to see the effect. The app never writes overrides; persisted icon
changes are edits to this file.
"""

from __future__ import annotations

from enum import Enum

_overrides: dict["Icon", str] = {}


def set_icon_override(icon: "Icon", glyph: str) -> None:
    """Tooling only: make ``icon.glyph()`` return ``glyph`` in this process."""
    _overrides[icon] = glyph


def reset_icon_overrides() -> None:
    """Tooling only: drop every override set in this process."""
    _overrides.clear()


class Icon(Enum):
    # Dashboard chrome
    SETTINGS_GEAR = "\ue8b8"  # dashboard footer Setup button

    # Header / navigation
    BACK = "\ue166"  # Setup back (restore-arrow)
    CLOSE = "\ue5cd"  # EnterIP / Wi-Fi close (X)
    CHEVRON_RIGHT = "\ue5cc"  # setup row trailing chevron

    # Setup rows
    TELEMETRY_MODE = "\ue51e"
    BRIGHTNESS = "\ue518"
    REFERENCE_LAP = "\ue425"
    STATUS_LIGHTS = "\ue0f0"
    NETWORK = "\ue63e"  # wifi
    FACTORY_RESET = "\ue8ba"  # settings_backup_restore

    # Controls
    CARET_DOWN = "\ue313"  # dropdown chevron
    MINUS = "\ue15b"  # brightness stepper
    PLUS = "\ue145"
    BACKSPACE = "\ue14a"
    OK_CHECK = "\ue5ca"  # EnterIP confirm

    # Wi-Fi flow
    RESCAN = "\ue5d5"  # refresh
    CONNECTED = "\ue86c"  # check_circle, the big success glyph
    ROW_CHECK = "\ue876"  # done, current-network marker
    LOCK = "\ue897"  # secured network
    SHIFT = "\ue5d8"  # arrow_upward, keyboard shift
    REVEAL = "\ue8f4"  # visibility, password reveal

    def glyph(self) -> str:
        override = _overrides.get(self)
        return self.value if override is None else override
