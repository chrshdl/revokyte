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
