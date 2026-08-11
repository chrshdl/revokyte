"""Preview the Wi-Fi scan-result list in a desktop window.

Renders WifiSetupView's scan phase the way WifiSetupState shows it — header,
rescan control, and the network list — populated with fake scan results that
cover every visual variant: 4..0 signal bars, secured/open, the
connected-SSID marker, and a long SSID. Scrolling and taps work (tapped rows
just post their events into the void). Close the window or press Esc/Q to
quit.

Usage (from the repo root, venv active):

    python tools/preview_wifi_scan_list.py
    python tools/preview_wifi_scan_list.py --boot      # first-boot variant (Skip instead of Back)
    python tools/preview_wifi_scan_list.py --empty     # "No networks found" copy
    python tools/preview_wifi_scan_list.py --scanning  # "Scanning for networks ..." copy
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pygame  # noqa: E402

from instrument_cluster.core.system.wifi_manager import Network  # noqa: E402
from instrument_cluster.peripherals.display import Display  # noqa: E402
from instrument_cluster.ui.views.wifi_setup_view import WifiSetupView  # noqa: E402

# One row per visual variant the list can render.
FAKE_NETWORKS = [
    Network(ssid="Pit Wall 5G", secured=True, signal_dbm=-48),  # 4 bars, lock
    Network(ssid="Paddock Guest", secured=False, signal_dbm=-60),  # 3 bars, open
    Network(ssid="Garage 42", secured=True, signal_dbm=-72),  # 2 bars
    Network(
        ssid="A very long network name that should truncate",
        secured=True,
        signal_dbm=-80,  # 1 bar
    ),
    Network(ssid="Marshal Post 7", secured=False, signal_dbm=-92),  # 0 bars
    Network(ssid="Race Control", secured=True, signal_dbm=-58),  # scroll filler
    Network(ssid="Timing Loop", secured=True, signal_dbm=-70),
    Network(ssid="Podium Cam", secured=False, signal_dbm=-84),
]
CONNECTED_SSID = "Pit Wall 5G"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default="dev", help="display profile")
    parser.add_argument(
        "--boot",
        action="store_true",
        help="first-boot entry: Skip control instead of Back",
    )
    variant = parser.add_mutually_exclusive_group()
    variant.add_argument(
        "--empty", action="store_true", help="empty scan result instead of the list"
    )
    variant.add_argument(
        "--scanning", action="store_true", help="the scanning-in-progress status"
    )
    args = parser.parse_args()

    pygame.init()
    display = Display(args.display)
    surface = display.surface

    # Mirror WifiSetupState: Back when entered from settings, Skip on the
    # first-boot gate.
    view = WifiSetupView(show_back=not args.boot, show_skip=args.boot)
    if args.scanning:
        view.show_scanning()
    elif args.empty:
        view.show_networks([])
    else:
        view.show_networks(FAKE_NETWORKS, CONNECTED_SSID)

    background = pygame.Surface(surface.get_size())
    background.fill(view.background_color)
    view.draw_static_elements(background)
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
            view.handle_event(event)
        view.update(dt)
        display.present(view.draw(surface, background))

    pygame.quit()


if __name__ == "__main__":
    main()
