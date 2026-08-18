"""WifiSetupView's header controls.

The "Use demo" skip button was removed: it was only ever shown on the
first-boot gate, and the device now requires a Wi-Fi connection before
continuing there. The header must never offer anything but Scan (plus Back
where applicable).
"""

import pytest

from instrument_cluster.ui.views.wifi_setup_view import WifiSetupView
from instrument_cluster.ui.widgets.base.button import Button


def test_scan_controls_only_ever_include_rescan():
    view = WifiSetupView(show_back=False)
    controls = view._scan_controls()
    assert len(controls) == 1
    assert controls[0].text == "Scan"


def test_show_networks_header_has_no_skip_button():
    view = WifiSetupView(show_back=False)
    view.show_networks([])
    buttons = [w for w in view._widgets if isinstance(w, Button)]
    assert len(buttons) == 1
    assert buttons[0].text == "Scan"


def test_show_scanning_header_has_no_skip_button():
    view = WifiSetupView(show_back=False)
    view.show_scanning()
    buttons = [w for w in view._widgets if isinstance(w, Button)]
    assert len(buttons) == 1
    assert buttons[0].text == "Scan"


def test_show_skip_kwarg_removed():
    with pytest.raises(TypeError):
        WifiSetupView(show_back=False, show_skip=True)
