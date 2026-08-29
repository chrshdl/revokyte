"""Drive the whole Wi-Fi setup flow on the desktop, against a fake radio.

Runs the real :class:`WifiSetupState` — real scan/password/status phases,
real keyboard, real connect worker — with a stubbed WifiManager, so the
appliance's provisioning flow can be clicked through (and debugged) without
a Pi. Every state transition is printed with a timestamp, which is what
makes it useful: if pressing OK does something other than show
"Connecting to …", the trace says exactly what ran instead.

Usage (from the repo root, venv active):

    python tools/preview_wifi_setup.py                 # association fails after --assoc-delay
    python tools/preview_wifi_setup.py --succeed       # associates and gets a lease
    python tools/preview_wifi_setup.py --no-dhcp       # associates, never leases
    python tools/preview_wifi_setup.py --boot          # first-boot entry (Skip instead of X)
    python tools/preview_wifi_setup.py --scan-secs 6   # slow scans, to provoke races

Click a network, type with the on-screen keyboard, press OK. Esc quits.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pygame  # noqa: E402

from instrument_cluster.core.system.wifi_manager import Network, WifiManager  # noqa: E402
from instrument_cluster.peripherals.display import Display  # noqa: E402
from instrument_cluster.states.wifi_setup_state import (  # noqa: E402
    ENTRY_BOOT,
    ENTRY_SETTINGS,
    WifiSetupState,
)

FAKE_NETWORKS = [
    Network(ssid="Pit Wall 5G", secured=True, signal_dbm=-48),
    Network(ssid="Paddock Guest", secured=False, signal_dbm=-60),
    Network(ssid="Garage 42", secured=True, signal_dbm=-72),
    Network(ssid="Marshal Post 7", secured=True, signal_dbm=-84),
    Network(ssid="Race Control", secured=True, signal_dbm=-58),
    Network(ssid="Timing Loop", secured=True, signal_dbm=-70),
]

_T0 = time.monotonic()


def log(msg: str) -> None:
    print(f"[{time.monotonic() - _T0:7.2f}s] {msg}", flush=True)


class FakeWifiManager(WifiManager):
    """A radio that behaves however the command line says."""

    def __init__(self, args, conf_path: str):
        super().__init__(conf_path=conf_path, country="")
        self._args = args
        self._associated_at: float | None = None

    available = True  # class attribute: shadows the real property

    def scan(self, settle: float = 2.5):
        log(f"manager.scan() started (takes {self._args.scan_secs}s)")
        time.sleep(self._args.scan_secs)
        log("manager.scan() returning networks")
        return list(FAKE_NETWORKS)

    def current_ssid(self):
        return "Pit Wall 5G" if self.is_associated() else ""

    def connect(self, ssid, psk):
        log(f"manager.connect(ssid={ssid!r}, psk={'*' * len(psk or '')})")
        self._associated_at = time.monotonic() + self._args.assoc_delay

    def is_associated(self) -> bool:
        if self._args.fail_auth or self._associated_at is None:
            return False
        return time.monotonic() >= self._associated_at

    def is_connected(self) -> bool:
        return self.is_associated() and not self._args.no_dhcp

    def request_dhcp(self) -> None:
        log("manager.request_dhcp() (networkctl kick)")

    def link_state(self) -> str:
        return "carrier/configuring" if self._args.no_dhcp else "routable/configured"

    def ipv4_address(self):
        return "10.22.33.85" if self.is_connected() else None


class TracingStateManager:
    """Stands in for StateManager and narrates what the state asks of it."""

    def pop_state(self):
        log("state_manager.pop_state()  <- leaving Wi-Fi setup")

    def change_state(self, state):
        log(f"state_manager.change_state({type(state).__name__})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default="dev", help="display profile")
    parser.add_argument("--boot", action="store_true", help="first-boot entry")
    parser.add_argument("--succeed", action="store_true", help="connect successfully")
    parser.add_argument("--fail-auth", action="store_true", help="never associate")
    parser.add_argument("--no-dhcp", action="store_true", help="associate, never lease")
    parser.add_argument("--scan-secs", type=float, default=2.5, help="scan duration")
    parser.add_argument(
        "--assoc-delay", type=float, default=3.0, help="seconds until association"
    )
    args = parser.parse_args()
    if not (args.succeed or args.fail_auth or args.no_dhcp):
        args.fail_auth = True  # the failure the appliance actually showed

    pygame.init()
    display = Display(args.display)
    surface = display.surface

    manager = FakeWifiManager(args, conf_path="/tmp/preview-wpa_supplicant.conf")
    state = WifiSetupState(
        state_manager=TracingStateManager(),
        manager=manager,
        entry=ENTRY_BOOT if args.boot else ENTRY_SETTINGS,
    )

    state.enter(surface)

    background = pygame.Surface(surface.get_size())
    background.fill(state.background_color())
    state.background = background
    state.full_paint(surface)
    display.present_full()

    clock = pygame.time.Clock()
    last = (state.view.phase, state._connecting)
    running = True
    while running:
        dt = clock.tick(60) / 1000
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (
                event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
            ):
                running = False
            state.handle_event(event)
        state.update(dt)

        now = (state.view.phase, state._connecting)
        if now != last:
            log(
                f"phase={now[0]!r} connecting={now[1]} "
                f"status={state.view.status_message!r} hint={state.view.hint_message!r}"
            )
            last = now

        display.present(state.draw(surface))

    pygame.quit()


if __name__ == "__main__":
    main()
