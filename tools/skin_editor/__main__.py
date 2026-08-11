"""Launch the skin editor:  python tools/skin_editor [--skin ...] [--view ...]

Bootstrap order is load-bearing: config isolation (a temp config +
IC_CONFIG_PATH) must be in place *before* any ``instrument_cluster``
module is imported — ConfigManager resolves its path on first use, and the
editor must never touch the user's real config. Likewise the
``is_raspberry_pi`` patch, so SetupView shows the Pi-only rows.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO))  # so `tools.skin_editor.*` imports resolve


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skin",
        choices=["1280x720", "1024x600", "800x480"],
        default="1280x720",
        help="skin selected at startup",
    )
    parser.add_argument(
        "--view", default=None, help="view id selected at startup"
    )
    args = parser.parse_args()

    # Config isolation, before any instrument_cluster import.
    cfg_dir = tempfile.mkdtemp(prefix="skin_editor_")
    cfg_path = os.path.join(cfg_dir, "config.json")
    with open(cfg_path, "w") as fh:
        json.dump({"telemetry_mode": "demo", "status_lights": False}, fh)
    os.environ["IC_CONFIG_PATH"] = cfg_path

    import pygame

    pygame.init()

    # Show the Pi-only Setup rows (Brightness, Network) in the editor.
    from instrument_cluster.ui.views import setup_view

    setup_view.is_raspberry_pi = lambda: True

    from tools.skin_editor.app import EditorApp

    EditorApp(skin=args.skin, view=args.view).run()
    pygame.quit()


if __name__ == "__main__":
    main()
