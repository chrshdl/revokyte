from types import SimpleNamespace

import pytest

from instrument_cluster.core.system.wifi_manager import Network, WifiManager

SCAN_OUTPUT = """\
bssid / frequency / signal level / flags / ssid
00:11:22:33:44:55\t2412\t-45\t[WPA2-PSK-CCMP][ESS]\tFRITZ!Box 7590
66:77:88:99:aa:bb\t2437\t-70\t[WPA2-PSK-CCMP][ESS]\tVodafone-AB12
cc:dd:ee:ff:00:11\t2462\t-82\t[ESS]\tOpenGuest
22:33:44:55:66:77\t5180\t-40\t[WPA2-PSK-CCMP][ESS]\tFRITZ!Box 7590
33:44:55:66:77:88\t2412\t-60\t[ESS]\t
"""


def test_parse_scan_results_dedupes_and_sorts():
    nets = WifiManager._parse_scan_results(SCAN_OUTPUT)
    # hidden (blank) SSID dropped; duplicate FRITZ collapsed to strongest (-40)
    ssids = [n.ssid for n in nets]
    assert ssids == ["FRITZ!Box 7590", "Vodafone-AB12", "OpenGuest"]
    assert nets[0].signal_dbm == -40


def test_parse_scan_results_security_flags():
    nets = {n.ssid: n for n in WifiManager._parse_scan_results(SCAN_OUTPUT)}
    assert nets["FRITZ!Box 7590"].secured is True
    assert nets["OpenGuest"].secured is False


def test_parse_scan_results_decodes_escaped_ssid():
    # wpa_cli printf-escapes non-ASCII SSID bytes: ’ (U+2019) arrives as
    # \xe2\x80\x99. The list must show the character, not the escapes.
    out = (
        "bssid / frequency / signal level / flags / ssid\n"
        "00:11:22:33:44:55\t2412\t-50\t[WPA2-PSK-CCMP][ESS]\t"
        "Qiu\\xe2\\x80\\x99s Home\n"
    )
    nets = WifiManager._parse_scan_results(out)
    assert [n.ssid for n in nets] == ["Qiu’s Home"]


def test_decode_ssid():
    assert WifiManager._decode_ssid("plain ascii") == "plain ascii"
    assert WifiManager._decode_ssid("Qiu\\xe2\\x80\\x99s Home") == "Qiu’s Home"
    assert WifiManager._decode_ssid('a\\"b\\\\c') == 'a"b\\c'
    # invalid UTF-8 byte degrades to U+FFFD instead of raising
    assert WifiManager._decode_ssid("bad\\xffbyte") == "bad�byte"
    # control characters are neutralized — an embedded NUL would crash
    # pygame's text renderer, and SSIDs are untrusted broadcast data
    assert WifiManager._decode_ssid("evil\\x00ap") == "evil�ap"
    assert WifiManager._decode_ssid("two\\nlines") == "two�lines"
    assert WifiManager._decode_ssid("ansi\\e[31m") == "ansi�[31m"
    # trailing lone backslash and malformed \x pass through untouched
    assert WifiManager._decode_ssid("tail\\") == "tail\\"
    assert WifiManager._decode_ssid("no\\xZZhex") == "no\\xZZhex"


def test_parse_status():
    status = WifiManager._parse_status(
        "bssid=00:11:22:33:44:55\nssid=FRITZ!Box 7590\nwpa_state=COMPLETED\nip_address=192.168.1.50\n"
    )
    assert status["wpa_state"] == "COMPLETED"
    assert status["ip_address"] == "192.168.1.50"
    assert status["ssid"] == "FRITZ!Box 7590"


def test_build_config_secured():
    conf = WifiManager._build_config("MyNet", "s3cr3tpass", "DE")
    assert 'ssid="MyNet"' in conf
    assert "key_mgmt=WPA-PSK" in conf
    assert "country=DE" in conf
    assert "ctrl_interface=/run/wpa_supplicant" in conf
    # PSK must be the 64-char hex hash, never the plaintext passphrase
    expected_hex = WifiManager._hash_psk("MyNet", "s3cr3tpass")
    assert f"    psk={expected_hex}" in conf
    assert "s3cr3tpass" not in conf


def test_build_config_open_network():
    conf = WifiManager._build_config("OpenGuest", None, "DE")
    assert "key_mgmt=NONE" in conf
    assert "psk=" not in conf


def test_build_config_psk_is_hex_not_quoted():
    conf = WifiManager._build_config("MyNet", "s3cr3tpass", "DE")
    # Unquoted 64-char hex — wpa_supplicant interprets this as raw PSK
    for line in conf.splitlines():
        if line.strip().startswith("psk="):
            value = line.strip()[len("psk="):]
            assert len(value) == 64
            assert all(c in "0123456789abcdef" for c in value)


def test_build_config_escapes_ssid_quotes():
    conf = WifiManager._build_config('Net"With\\Specials', "password1", "DE")
    assert r'ssid="Net\"With\\Specials"' in conf


def test_network_bars_buckets():
    assert Network("a", True, -40).bars == 4
    assert Network("a", True, -60).bars == 3
    assert Network("a", True, -75).bars == 2
    assert Network("a", True, -85).bars == 1
    assert Network("a", True, -95).bars == 0


def test_build_config_sae_is_wpa3_only_with_required_pmf():
    conf = WifiManager._build_config("MyNet", "s3cr3tpass", "DE", sae=True)
    assert "key_mgmt=SAE" in conf
    assert "ieee80211w=2" in conf  # WPA3 mandates PMF
    # SAE authenticates with the raw passphrase, not the hash.
    assert 'sae_password="s3cr3tpass"' in conf
    assert "psk=" not in conf


def test_build_config_default_stays_plain_wpa_psk():
    conf = WifiManager._build_config("MyNet", "s3cr3tpass", "DE", sae=False)
    assert "key_mgmt=WPA-PSK\n" in conf
    assert "sae_password" not in conf
    assert "ieee80211w" not in conf
    import hashlib
    expected = hashlib.pbkdf2_hmac(
        "sha1", b"s3cr3tpass", b"MyNet", 4096, 32
    ).hex()
    assert f"psk={expected}" in conf


def test_build_config_open_network_ignores_sae():
    conf = WifiManager._build_config("OpenGuest", None, "DE", sae=True)
    assert "key_mgmt=NONE" in conf
    assert "sae_password" not in conf


# --- AKM selection: SAE only where the AP leaves no alternative ---

_TRANSITION = "aa:bb:cc:dd:ee:ff\t5180\t-48\t[WPA2-PSK+SAE-CCMP][ESS][MFPC]\tMyNet\n"
_WPA3_ONLY = "aa:bb:cc:dd:ee:ff\t5180\t-48\t[WPA2-SAE-CCMP][ESS][MFPR][MFPC]\tMyNet\n"
_WPA2_ONLY = "aa:bb:cc:dd:ee:ff\t5180\t-48\t[WPA2-PSK-CCMP][ESS]\tMyNet\n"


def _manager_seeing(monkeypatch, scan_line):
    mgr = WifiManager()
    mgr._supports_sae_cached = True
    monkeypatch.setattr(
        mgr, "_wpa_cli", lambda *a, **k: "bssid\tfreq\tsignal\tflags\tssid\n" + scan_line
    )
    return mgr


def test_transition_ap_keeps_wpa_psk(monkeypatch):
    """The AP offers both: take WPA-PSK. SAE drags in PMF, and on this
    hardware that combination associates without passing traffic."""
    mgr = _manager_seeing(monkeypatch, _TRANSITION)
    assert mgr._use_sae("MyNet", "s3cr3tpass") is False


def test_wpa3_only_ap_uses_sae(monkeypatch):
    mgr = _manager_seeing(monkeypatch, _WPA3_ONLY)
    assert mgr._use_sae("MyNet", "s3cr3tpass") is True


def test_wpa2_only_ap_uses_wpa_psk(monkeypatch):
    mgr = _manager_seeing(monkeypatch, _WPA2_ONLY)
    assert mgr._use_sae("MyNet", "s3cr3tpass") is False


def test_unknown_ssid_falls_back_to_wpa_psk(monkeypatch):
    mgr = _manager_seeing(monkeypatch, _WPA3_ONLY)
    assert mgr._use_sae("SomeOtherNet", "s3cr3tpass") is False


def test_open_network_never_uses_sae(monkeypatch):
    mgr = _manager_seeing(monkeypatch, _WPA3_ONLY)
    assert mgr._use_sae("MyNet", None) is False


def test_wpa3_only_ap_without_supplicant_support_stays_psk(monkeypatch):
    mgr = _manager_seeing(monkeypatch, _WPA3_ONLY)
    mgr._supports_sae_cached = False
    assert mgr._use_sae("MyNet", "s3cr3tpass") is False


def test_supports_sae_parses_capability(monkeypatch):
    mgr = WifiManager()
    monkeypatch.setattr(
        mgr, "_wpa_cli", lambda *a, **k: "WPA-PSK WPA-EAP SAE OWE\n"
    )
    assert mgr.supports_sae() is True
    # cached: a later failing wpa_cli must not flip the answer
    monkeypatch.setattr(mgr, "_wpa_cli", lambda *a, **k: (_ for _ in ()).throw(OSError))
    assert mgr.supports_sae() is True


def test_supports_sae_false_without_sae(monkeypatch):
    mgr = WifiManager()
    monkeypatch.setattr(mgr, "_wpa_cli", lambda *a, **k: "WPA-PSK WPA-EAP\n")
    assert mgr.supports_sae() is False


def test_supports_sae_probe_failure_falls_back_uncached(monkeypatch):
    mgr = WifiManager()
    monkeypatch.setattr(
        mgr, "_wpa_cli", lambda *a, **k: (_ for _ in ()).throw(OSError("no ctrl"))
    )
    assert mgr.supports_sae() is False
    # transient failure was not cached: a working probe later succeeds
    monkeypatch.setattr(mgr, "_wpa_cli", lambda *a, **k: "SAE\n")
    assert mgr.supports_sae() is True


def test_build_config_no_country_omits_the_line():
    conf = WifiManager._build_config("MyNet", "s3cr3tpass", "")
    assert "country=" not in conf
    assert conf.startswith("ctrl_interface=/run/wpa_supplicant\nupdate_config=1\n\n")


def test_build_config_country_override_pins_the_domain():
    conf = WifiManager._build_config("MyNet", "s3cr3tpass", "GB")
    assert "country=GB\n" in conf


def test_manager_country_from_config_override(tmp_path, monkeypatch):
    from instrument_cluster.config import ConfigManager

    original = ConfigManager.path
    ConfigManager.reset()
    ConfigManager.set_path(tmp_path / "config.json")
    (tmp_path / "config.json").write_text('{"wifi_country": "GB"}')
    try:
        assert WifiManager().country == "GB"
        (tmp_path / "config.json").write_text("{}")
        ConfigManager.reset()
        assert WifiManager().country == ""
    finally:
        ConfigManager.reset()
        ConfigManager.set_path(original)


# --- lease detection / networkd control ---


def test_is_connected_uses_kernel_address_when_status_lacks_ip(monkeypatch):
    """wpa_cli only reports ip_address= while its l2 socket can read one;
    a lease must still be detected without it."""
    mgr = WifiManager()
    monkeypatch.setattr(mgr, "status", lambda: {"wpa_state": "COMPLETED"})
    monkeypatch.setattr(mgr, "ipv4_address", lambda: "10.22.33.85")
    assert mgr.is_connected() is True


def test_is_connected_false_without_association(monkeypatch):
    mgr = WifiManager()
    monkeypatch.setattr(mgr, "status", lambda: {"wpa_state": "SCANNING"})
    monkeypatch.setattr(mgr, "ipv4_address", lambda: "10.22.33.85")
    assert mgr.is_connected() is False


def test_is_connected_false_when_associated_without_lease(monkeypatch):
    mgr = WifiManager()
    monkeypatch.setattr(mgr, "status", lambda: {"wpa_state": "COMPLETED"})
    monkeypatch.setattr(mgr, "ipv4_address", lambda: None)
    assert mgr.is_connected() is False


def test_link_state_reads_last_two_columns(monkeypatch):
    mgr = WifiManager()
    mgr._networkctl_bin = "/usr/bin/networkctl"
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="  3 wlan0 wlan routable configured\n", stderr=""
        ),
    )
    assert mgr.link_state() == "routable/configured"


def test_link_state_tolerates_default_route_marker(monkeypatch):
    mgr = WifiManager()
    mgr._networkctl_bin = "/usr/bin/networkctl"
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="* 3 wlan0 wlan carrier configuring\n", stderr=""
        ),
    )
    assert mgr.link_state() == "carrier/configuring"


def test_link_state_empty_without_networkctl():
    mgr = WifiManager()
    mgr._networkctl_bin = None
    assert mgr.link_state() == ""


def test_request_dhcp_falls_back_to_renew(monkeypatch):
    mgr = WifiManager()
    mgr._networkctl_bin = "/usr/bin/networkctl"
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[1])
        # reconfigure unsupported on older systemd, renew works
        rc = 1 if cmd[1] == "reconfigure" else 0
        return SimpleNamespace(returncode=rc, stdout="", stderr="unknown verb")

    monkeypatch.setattr("subprocess.run", fake_run)
    mgr.request_dhcp()
    assert calls == ["reconfigure", "renew"]


def test_request_dhcp_stops_after_success(monkeypatch):
    mgr = WifiManager()
    mgr._networkctl_bin = "/usr/bin/networkctl"
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[1])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    mgr.request_dhcp()
    assert calls == ["reconfigure"]


def test_request_dhcp_noop_without_networkctl(monkeypatch):
    mgr = WifiManager()
    mgr._networkctl_bin = None
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: pytest.fail("must not shell out without networkctl"),
    )
    mgr.request_dhcp()  # must not raise


def test_diagnostics_collects_networkd_and_supplicant_journals(monkeypatch):
    mgr = WifiManager()
    mgr._networkctl_bin = "/usr/bin/networkctl"
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(" ".join(cmd))
        return SimpleNamespace(returncode=0, stdout=f"output of {cmd[0]}\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    report = mgr.diagnostics()

    assert any("networkctl status" in c for c in seen)
    assert any("systemd-networkd" in c for c in seen)
    assert any("wpa_supplicant@wlan0" in c for c in seen)
    assert "output of" in report


def test_diagnostics_survives_missing_tools(monkeypatch):
    mgr = WifiManager()
    mgr._networkctl_bin = None
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("journalctl")),
    )
    report = mgr.diagnostics()  # must not raise
    assert "journalctl" in report
