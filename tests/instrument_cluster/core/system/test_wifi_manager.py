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


def test_build_config_sae_offers_wpa2_and_wpa3():
    """Transition-capable: wpa_supplicant picks SAE where the AP offers it
    and WPA-PSK where it doesn't, so one config serves every network."""
    conf = WifiManager._build_config("MyNet", "s3cr3tpass", "DE", sae=True)
    assert "key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE" in conf
    assert "ieee80211w=1" in conf  # PMF available; SAE requires it anyway
    # SAE authenticates with the raw passphrase, WPA-PSK with the hash.
    assert 'sae_password="s3cr3tpass"' in conf
    import hashlib
    expected = hashlib.pbkdf2_hmac("sha1", b"s3cr3tpass", b"MyNet", 4096, 32).hex()
    assert f"psk={expected}" in conf


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
