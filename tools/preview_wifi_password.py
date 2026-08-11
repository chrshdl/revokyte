"""Preview the Wi-Fi password-entry screen in a desktop window.

Renders WifiSetupView's password phase — SSID/password fields fed by the
on-screen QWERTY keyboard — with the keyboard fully functional: this script
replicates WifiSetupState's key handling (insert, backspace, shift, mode,
reveal), so typing, masking, and the hint line can all be checked without a
Pi. Tap a field to focus it. Connect replays the state's validation, so the
"Password must be 8+ characters" hint renders too. Close the window or
press Esc to quit (Q types a q!).

Usage (from the repo root, venv active):

    python tools/preview_wifi_password.py                    # picked "Pit Wall 5G" from the scan
    python tools/preview_wifi_password.py --ssid "Garage 42"
    python tools/preview_wifi_password.py --manual           # hidden SSID: editable network field
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pygame  # noqa: E402

from instrument_cluster.peripherals.display import Display  # noqa: E402
from instrument_cluster.ui.events import (  # noqa: E402
    WIFI_BACKSPACE_RELEASED,
    WIFI_CONNECT_RELEASED,
    WIFI_KEY_RELEASED,
    WIFI_MODE_RELEASED,
    WIFI_REVEAL_RELEASED,
    WIFI_SHIFT_RELEASED,
)
from instrument_cluster.ui.views.wifi_setup_view import WifiSetupView  # noqa: E402

_MIN_PSK_LEN = 8  # mirrors wifi_setup_state._MIN_PSK_LEN


def handle_keyboard_event(view: WifiSetupView, event) -> None:
    """The password-phase slice of WifiSetupState.handle_event."""
    if event.type == WIFI_KEY_RELEASED:
        field = view.active_field()
        label = getattr(event, "label", "")
        if field is not None and label:
            field.set_text(field.text + label)
    elif event.type == WIFI_BACKSPACE_RELEASED:
        field = view.active_field()
        if field is not None and field.text:
            field.set_text(field.text[:-1])
    elif event.type == WIFI_SHIFT_RELEASED:
        view.toggle_shift()
    elif event.type == WIFI_MODE_RELEASED:
        view.toggle_mode()
    elif event.type == WIFI_REVEAL_RELEASED:
        view.toggle_reveal()
    elif event.type == WIFI_CONNECT_RELEASED:
        # Replay the state's validation so the hint line can be previewed.
        ssid = view.ssid_text() if view.ssid_field is not None else "preview"
        psk = view.password_text()
        if not ssid:
            view.set_hint("Enter a network name.")
        elif psk and len(psk) < _MIN_PSK_LEN:
            view.set_hint("Password must be 8+ characters.")
        else:
            view.set_hint("")
            print(f"[preview] would connect to {ssid!r} with psk={psk!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default="dev", help="display profile")
    parser.add_argument("--ssid", default="Pit Wall 5G", help="picked network's SSID")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="hidden-SSID manual entry: editable network field",
    )
    args = parser.parse_args()

    pygame.init()
    display = Display(args.display)
    surface = display.surface

    view = WifiSetupView(show_back=True, show_skip=False)
    if args.manual:
        view.show_password(None, secured=True, manual=True)
    else:
        view.show_password(args.ssid, secured=True, manual=False)

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
                event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
            ):
                running = False
            view.handle_event(event)
            handle_keyboard_event(view, event)
        view.update(dt)
        display.present(view.draw(surface, background))

    pygame.quit()


if __name__ == "__main__":
    main()
