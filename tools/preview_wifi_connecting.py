"""Preview the Wi-Fi connecting screen in a desktop window.

Renders WifiSetupView in its status phase — a centred message with the header
shown — so fonts and copy can be checked without a Pi. The screen has no
interactive widgets; close the window or press Esc/Q to quit.

The boot-time "Connecting to Wi-Fi" pill itself is WifiStatusWindow; preview
that with tools/preview_wifi_connecting_pill.py.

Usage (from the repo root, venv active):

    python tools/preview_wifi_connecting.py
    python tools/preview_wifi_connecting.py --text "Verbinde mit WLAN ..."
    python tools/preview_wifi_connecting.py --error   # error styling variant
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pygame

from instrument_cluster.peripherals.display import Display
from instrument_cluster.ui.views.wifi_setup_view import (
    WifiSetupContext,
    WifiSetupView,
)

DEFAULT_TEXT = "Please wait ..."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default="dev", help="display profile")
    parser.add_argument(
        "--text", default=DEFAULT_TEXT, help="status message to display"
    )
    parser.add_argument(
        "--error", action="store_true", help="render with error styling"
    )
    args = parser.parse_args()

    pygame.init()
    display = Display(args.display)
    surface = display.surface

    # Status phase with the header shown. This view paints no static
    # elements, so the background stays a plain fill.
    view = WifiSetupView()
    view.reset(WifiSetupContext(show_back=False))
    view.show_status(args.text, error=args.error, show_header=True)

    background = pygame.Surface(surface.get_size())
    background.fill(view.background_color)
    view.full_paint(surface, background)
    display.present_full()

    clock = pygame.time.Clock()
    running = True
    while running:
        dt = clock.tick(60) / 1000
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (
                event.type == pygame.KEYDOWN
                and event.key in (pygame.K_ESCAPE, pygame.K_q)
            ):
                running = False
        view.update(dt)
        display.present(view.draw(surface, background))

    pygame.quit()


if __name__ == "__main__":
    main()
