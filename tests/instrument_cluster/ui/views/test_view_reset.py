"""Every pooled view must come back from reset() looking freshly built.

A view now outlives the state that dirtied it, so anything the last visit
left behind — a scroll offset, an open menu, an error label, a typed
password — is visible on the next visit unless reset() clears it. These are
the regressions that pooling introduces; each one is a screen the driver
would see in a wrong state.
"""

import pygame
import pytest

from instrument_cluster.config import ConfigManager
from instrument_cluster.telemetry.mode import DiffReferenceMode, TelemetryMode
from instrument_cluster.ui.views.enter_ip_view import EnterIPContext, EnterIPView
from instrument_cluster.ui.views.install_view import InstallContext, InstallView
from instrument_cluster.ui.views.setup_view import SetupView
from instrument_cluster.ui.views.software_view import SoftwareView
from instrument_cluster.ui.views.wifi_setup_view import (
    WifiSetupContext,
    WifiSetupView,
)


@pytest.fixture(autouse=True)
def config_path(tmp_path):
    ConfigManager.set_path(tmp_path / "config.json")
    ConfigManager.reset()
    yield


# --------------------------------------------------------------------------
# WifiSetupView — the one with a credential in it
# --------------------------------------------------------------------------
def test_a_typed_wifi_password_never_survives_into_the_next_visit():
    """The important one. WifiSetupState reads view.phase as authoritative,
    so a view left in PHASE_PASSWORD re-opens straight onto the keyboard —
    with the previous visit's password still in the field."""
    view = WifiSetupView()
    view.reset(WifiSetupContext(show_back=True))

    view.show_password("HomeNetwork", secured=True, manual=False)
    view.password_field.set_text("hunter2-the-real-one")
    assert view.phase == WifiSetupView.PHASE_PASSWORD

    view.reset(WifiSetupContext(show_back=True))

    assert view.phase == WifiSetupView.PHASE_SCAN
    assert view.password_field is None
    assert view.ssid_field is None
    assert view._focused is None


def test_wifi_reset_clears_a_status_and_its_error_styling():
    view = WifiSetupView()
    view.show_status("Wrong  password", error=True)

    view.reset(WifiSetupContext())

    assert view.status_message == ""
    assert view.status_is_error is False
    assert view.hint_message == ""


def test_show_back_comes_from_the_context_not_the_constructor():
    view = WifiSetupView()

    view.reset(WifiSetupContext(show_back=False))
    assert view.show_back is False

    view.reset(WifiSetupContext(show_back=True))
    assert view.show_back is True


# --------------------------------------------------------------------------
# SetupView — the screen in the reported stall
# --------------------------------------------------------------------------
def test_setup_reset_returns_the_list_to_the_top():
    view = SetupView()
    view.scrollbar.offset = 120.0
    view.rows.scroll_to(120.0)

    view.reset()

    assert view.scrollbar.offset == 0.0


def test_setup_reset_closes_an_open_dropdown():
    view = SetupView()
    view.telemetry_mode_dropdown._set_open(True)

    view.reset()

    assert view.telemetry_mode_dropdown.open is False


def test_setup_dropdowns_track_config_changed_while_setup_was_closed():
    """The install flow writes telemetry_mode/feed from another screen, and
    the reference-lap mode can be changed and come back. A pooled view would
    still show whatever was selected when it was first built."""
    view = SetupView()
    ConfigManager.set_diff_reference_mode(DiffReferenceMode.PREVIOUS.value)

    view.reset()

    selected = view.diff_reference_mode_dropdown.selected_index
    assert view.DIFF_REFERENCE_OPTIONS[selected] is DiffReferenceMode.PREVIOUS


def test_setup_toggles_track_config(monkeypatch):
    view = SetupView()
    before = ConfigManager.get_config().status_lights

    ConfigManager.set_status_lights(not before)
    view.reset()

    assert view.status_lights_toggle.checked is (not before)


def test_the_telemetry_row_relabels_when_the_feed_goes_stale(monkeypatch):
    """"Telemetry (update)" is how a feed left by an earlier image is
    surfaced. It is decided from config at build time, so a pooled view has
    to re-decide it on every entry."""
    import instrument_cluster.ui.views.setup_view as module

    view = SetupView()
    monkeypatch.setattr(module, "feed_needs_reinstall", lambda feed, ver: "0.9.0")
    ConfigManager.set_telemetry_mode(TelemetryMode.UDP)

    view.reset()

    assert view._telemetry_caption.text == "Telemetry (update)"


def test_an_extension_row_label_is_re_evaluated_on_every_entry():
    """button_text may be a callable precisely so the label can track live
    extension state (Pro's licence row reads its tier that way)."""
    from instrument_cluster.extensions import SetupEntry
    from instrument_cluster.extensions import runtime as extensions

    tier = {"value": "Enter Key"}
    entry = SetupEntry(
        icon="",
        label="Licence",
        button_text=lambda: tier["value"],
        make_state=lambda sm: None,
    )
    extensions.setup_entries.append(entry)
    try:
        view = SetupView()
        assert view._extension_rows[0][1].text == "Enter Key"

        tier["value"] = "Pro License"
        view.reset()

        assert view._extension_rows[0][1].text == "Pro License"
    finally:
        extensions.setup_entries.remove(entry)


# --------------------------------------------------------------------------
# SoftwareView — an armed destructive action
# --------------------------------------------------------------------------
def test_a_left_over_armed_factory_reset_is_disarmed(monkeypatch):
    """Armed, the *first* tap of the next visit would be the destructive
    one. The state disarms on exit; reset() is the belt to that braces."""
    import instrument_cluster.ui.views.software_view as module

    monkeypatch.setattr(module, "is_raspberry_pi", lambda: True)
    view = SoftwareView()
    view.set_factory_reset_armed(True)
    assert view.factory_reset_button.text == SoftwareView._FACTORY_RESET_ARMED_TEXT

    view.reset()

    assert view.factory_reset_button.text == SoftwareView._FACTORY_RESET_IDLE_TEXT


def test_software_reset_returns_the_list_to_the_top():
    view = SoftwareView()
    view.scrollbar.offset = 90.0

    view.reset()

    assert view.scrollbar.offset == 0.0


# --------------------------------------------------------------------------
# EnterIPView — variable-length recent list, and a prefilled field
# --------------------------------------------------------------------------
def test_recent_connections_are_retexted_not_rebuilt():
    view = EnterIPView()
    built = list(view.recent_buttons)

    view.reset(EnterIPContext(recent_connected=["10.0.0.5", "10.0.0.6"]))

    assert view.recent_buttons == built, "reset() must not allocate buttons"
    assert [b.text for b in view.recent_buttons[:2]] == ["10.0.0.5", "10.0.0.6"]
    assert view.recent_buttons[2].visible == 0
    assert view.recent_label.visible == 1


def test_a_shorter_recent_list_hides_the_leftover_slots():
    view = EnterIPView()
    view.reset(EnterIPContext(recent_connected=["1.1.1.1", "2.2.2.2", "3.3.3.3"]))

    view.reset(EnterIPContext(recent_connected=["9.9.9.9"]))

    assert view.recent_buttons[0].visible == 1
    assert [b.visible for b in view.recent_buttons[1:]] == [0, 0]
    assert all(b.event_data["label"] == "" for b in view.recent_buttons[1:])


def test_the_title_follows_the_context():
    view = EnterIPView()

    view.reset(EnterIPContext(title="Enter PC IP"))
    assert view.title_label.text == "Enter PC IP"

    view.reset(EnterIPContext())
    assert view.title_label.text == "Enter Playstation IP"


# --------------------------------------------------------------------------
# InstallView — the one whose widget *set* changes with its context
# --------------------------------------------------------------------------
def test_install_view_switches_between_updating_and_asking():
    view = InstallView()

    view.reset(InstallContext(feed_label="Forza", updating=True))
    assert len(view.btns.sprites()) == 1, "an update offers Cancel alone"
    assert view.title_label.text == "Updating UDP Telemetry"

    view.reset(InstallContext(feed_label="GT7", updating=False))
    assert len(view.btns.sprites()) == 2
    assert view.title_label.text == "Install UDP Telemetry?"
    assert "GT7" in " ".join(lbl.text for lbl in view.info_labels)


def test_a_failed_install_error_does_not_greet_the_next_visit():
    view = InstallView()
    view.set_error("Install failed.")

    view.reset(InstallContext(feed_label="GT7"))

    assert view.error_label.text == ""
    assert view.status_label.text == ""


# --------------------------------------------------------------------------
# Shared: a stuck press
# --------------------------------------------------------------------------
def test_reset_clears_a_button_left_pressed_by_its_own_transition():
    """Back/OK push the next state from their released handler, which leaves
    the button pressed on a view that is no longer on screen."""
    from instrument_cluster.ui.widgets.base.button import ButtonState

    view = SetupView()
    # Set directly rather than synthesising a tap: what is under test is that
    # reset() clears the state, not how it got there.
    view.back_button.state = ButtonState.PRESSED
    view.back_button._pressed_time = 3.0
    assert view.back_button.is_pressed()

    view.reset()

    assert not view.back_button.is_pressed()
    assert view.back_button._pressed_time == 0.0
