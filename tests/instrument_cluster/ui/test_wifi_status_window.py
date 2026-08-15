"""WifiStatusWindow — the boot-time "Connecting to Wi-Fi" pill.

The regression pinned here: on a credentials-provisioned boot no scan ever
runs, so a supplicant that raced udev at boot (dead, no Restart= in the
template unit) was never revived — the device stayed offline until someone
opened Wi-Fi setup by hand. The poller thread must heal the supplicant via
ensure_supplicant() before settling into the association poll.
"""
import threading
import time

import pytest

import instrument_cluster.ui.wifi_status_window as wsw
from instrument_cluster.ui.wifi_status_window import WifiStatusWindow


class _State:
    allows_system_alert = True


class _StateManager:
    current_state = _State()


class _Manager:
    """Stands in for WifiManager on an appliance mid-association."""

    def __init__(self, associate_after_ensure=True):
        self.available = True
        self.ensure_calls = 0
        self.ensured = threading.Event()
        self._associated = False
        self._associate_after_ensure = associate_after_ensure

    def is_associated(self):
        return self._associated

    def ensure_supplicant(self, wait=8.0):
        self.ensure_calls += 1
        self.ensured.set()
        if self._associate_after_ensure:
            self._associated = True
        return True


def _wait(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_poller_heals_supplicant_before_polling(monkeypatch):
    monkeypatch.setattr(wsw, "_POLL_FAST", 0.01)
    manager = _Manager()
    window = WifiStatusWindow(manager, _StateManager())

    assert manager.ensured.wait(2.0), "poller never called ensure_supplicant"
    assert manager.ensure_calls == 1
    # After the heal the (fake) association succeeds and the pill withdraws.
    assert _wait(lambda: not window.visible)


def test_already_associated_boot_skips_poller_and_heal():
    manager = _Manager()
    manager._associated = True
    window = WifiStatusWindow(manager, _StateManager())

    assert not window.visible
    time.sleep(0.05)
    assert manager.ensure_calls == 0


def test_dev_machine_without_wlan0_is_inert():
    manager = _Manager()
    manager.available = False
    window = WifiStatusWindow(manager, _StateManager())

    assert not window.visible
    time.sleep(0.05)
    assert manager.ensure_calls == 0
