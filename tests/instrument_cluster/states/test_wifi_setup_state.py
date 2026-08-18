"""First-boot Wi-Fi gate: no offline skip, header shows only Scan.

The device used to offer a "Use demo" button on first boot that skipped
straight to offline/demo mode. That escape hatch is gone: the user must
connect to Wi-Fi before continuing, so ENTRY_BOOT hides both Back and Skip
and leaves only the Scan control in the header.
"""

from instrument_cluster.states.wifi_setup_state import (
    ENTRY_BOOT,
    ENTRY_SETTINGS,
    WifiSetupState,
)
from instrument_cluster.ui import events as ui_events
from instrument_cluster.ui.widgets.base.button import Button


class _FakeWifiManager:
    available = True

    def current_ssid(self):
        return None

    def scan(self):
        return []


class _FakeStateManager:
    def pop_state(self):
        pass

    def change_state(self, state):
        pass


def _make_boot_state():
    return WifiSetupState(
        state_manager=_FakeStateManager(),
        manager=_FakeWifiManager(),
        entry=ENTRY_BOOT,
    )


def test_boot_entry_hides_back_and_skip_shows_only_scan():
    state = _make_boot_state()

    assert state.view.show_back is False

    buttons = [w for w in state.view._widgets if isinstance(w, Button)]
    assert len(buttons) == 1
    assert buttons[0].text == "Scan"


def test_settings_entry_shows_back_and_scan():
    """entry=ENTRY_SETTINGS is reachable from the Setup screen and must show
    a working Back control — regression test for a crash where
    _header_widgets() referenced a never-constructed _back_button."""
    state = WifiSetupState(
        state_manager=_FakeStateManager(),
        manager=_FakeWifiManager(),
        entry=ENTRY_SETTINGS,
    )

    assert state.view.show_back is True

    buttons = [w for w in state.view._widgets if isinstance(w, Button)]
    assert len(buttons) == 2


def test_skip_escape_hatch_removed():
    """Skip was only ever offered on first boot; once boot stopped showing
    it, it became unreachable from every entry and was removed outright."""
    state = _make_boot_state()

    assert not hasattr(state, "_on_skip")
    assert not hasattr(ui_events, "WIFI_SKIP_PRESSED")
    assert not hasattr(ui_events, "WIFI_SKIP_RELEASED")
