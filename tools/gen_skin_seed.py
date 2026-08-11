"""Seed a new skin module by scaling SKIN_1280 to a target resolution.

Usage:
    python tools/gen_skin_seed.py --size 1024x600 > /tmp/skin_1024.py
    mv /tmp/skin_1024.py src/instrument_cluster/ui/skins/skin_1024x600.py

The output is a mechanical starting point — per-axis-scaled and rounded,
with font sizes snapped to renderable integers (Pixeltype to multiples of
8, everything else to even sizes). It renders no worse than uniform
scaling would; the whole point of a skin is to then hand-tune the values
in place (or with tools/skin_editor).

The emission lives in ``instrument_cluster.ui.skins.serialize`` — the skin
editor saves through the same code path (with ``scale=None``, verbatim).

Note: importing the skins package requires every skin module it registers
to be importable, so redirect the output to a temp file and move it into
place — a shell ``>`` straight onto the target truncates it before this
script's own import runs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from instrument_cluster.ui.skins.serialize import emit_skin_module  # noqa: E402
from instrument_cluster.ui.skins.skin_1280x720 import SKIN_1280  # noqa: E402

# Fields whose seeded value is known to need hand work (structural
# decisions, pixel-font metrics) get a marker comment in the output.
_TUNE = frozenset(
    {
        "gear",
        "speed",
        "row_top",
        "row_pitch",
        "row_height",
        "visible_network_cells",
        "key_w",
        "key_h",
        "gap",
        "top",
        "row_step",
        "special_w",
        "space_w",
        "title_font_size",
        "header_font_size",
    }
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--size", required=True, help="target WxH, e.g. 800x480")
    args = ap.parse_args()

    w, h = (int(p) for p in args.size.split("x"))
    fx, fy = w / SKIN_1280.width, h / SKIN_1280.height
    fu = min(fx, fy)

    print(
        emit_skin_module(
            SKIN_1280,
            size=(w, h),
            scale=(fx, fy, fu),
            tune=_TUNE,
            docstring=(
                f"The {w}x{h} skin.\n\n"
                f"Seeded by tools/gen_skin_seed.py from SKIN_1280 (scale "
                f"{fx:.3f} x {fy:.3f});\nvalues marked TODO are mechanical "
                f"scalings pending hand-tuning on the panel.\n"
            ),
        ),
        end="",
    )


if __name__ == "__main__":
    main()
