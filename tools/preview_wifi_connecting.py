"""Preview the Wi-Fi connecting screen in a desktop window.

Renders exactly what WifiConnectingState shows at boot on the appliance —
WifiSetupView in its status phase — so fonts and copy can be checked without
a Pi. The screen has no interactive widgets; close the window or press
Esc/Q to quit.

Usage (from the repo root, venv active):

    python tools/preview_wifi_connecting.py
    python tools/preview_wifi_connecting.py --text "Verbinde mit WLAN ..."
    python tools/preview_wifi_connecting.py --error   # error styling variant
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pygame  # noqa: E402

from instrument_cluster.peripherals.display import Display  # noqa: E402
from instrument_cluster.ui.views.wifi_setup_view import WifiSetupView  # noqa: E402

# The text WifiConnectingState actually shows (states/wifi_connecting_state.py).
DEFAULT_TEXT = "Reconnecting to Wi-Fi, please wait ..."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--text", default=DEFAULT_TEXT, help="status message to display"
    )
    parser.add_argument(
        "--error", action="store_true", help="render with error styling"
    )
    args = parser.parse_args()

    pygame.init()
    display = Display("dev")
    surface = display.surface

    # Mirror WifiConnectingState: status phase with the header shown. Its
    # draw_static_background is a no-op, so no static elements are painted.
    view = WifiSetupView(show_back=False, show_skip=False)
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
                event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q)
            ):
                running = False
        view.update(dt)
        display.present(view.draw(surface, background))

    pygame.quit()


if __name__ == "__main__":
    main()
