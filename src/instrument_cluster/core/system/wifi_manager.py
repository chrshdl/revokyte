"""Runtime Wi-Fi provisioning for the instrument cluster.

The OS image (see instrument-cluster-os) drives the radio with
``wpa_supplicant@wlan0.service`` reading
``/etc/wpa_supplicant/wpa_supplicant-wlan0.conf`` (a symlink onto the
persistent ``/data`` partition), while ``systemd-networkd`` handles DHCP. Until
now those credentials had to be hand-written onto the boot partition before
flashing. This module lets the app provision them from the display instead:

* :meth:`WifiManager.scan` lists nearby networks via ``wpa_cli``.
* :meth:`WifiManager.connect` writes the persistent ``wpa_supplicant`` config
  and restarts the service so the network is joined now *and* on every reboot.
* :meth:`WifiManager.is_connected` reports association + DHCP state.

On a development machine (no ``wpa_cli``/``wlan0``) :attr:`available` is False
and the app skips the Wi-Fi gate entirely.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unicodedata
from dataclasses import dataclass

from ...logger import Logger

logger = Logger("wifi_manager").get()

DEFAULT_INTERFACE = "wlan0"
DEFAULT_CONF_PATH = "/etc/wpa_supplicant/wpa_supplicant-wlan0.conf"
DEFAULT_SERVICE = "wpa_supplicant@wlan0.service"

# wpa_supplicant's printf_encode() single-character escapes; everything else
# non-printable arrives as \xHH byte escapes.
_WPA_ESCAPES = {"n": 0x0A, "r": 0x0D, "t": 0x09, "e": 0x1B, "\\": 0x5C, '"': 0x22}


def _resolve_bin(name: str, *fallbacks: str) -> str | None:
    """Locate a binary by PATH, falling back to known absolute locations.

    systemd service units don't always carry ``/usr/sbin`` in ``PATH``; resolve
    explicitly so Wi-Fi support doesn't silently disappear when ``wpa_cli`` is
    only on ``sbin`` paths.
    """
    found = shutil.which(name)
    if found:
        return found
    for path in fallbacks:
        if os.path.exists(path):
            return path
    return None


@dataclass(frozen=True)
class Network:
    """A single scan result, deduplicated by SSID."""

    ssid: str
    secured: bool
    signal_dbm: int

    @property
    def bars(self) -> int:
        """Signal strength bucketed to 0..4 bars for display."""
        if self.signal_dbm >= -55:
            return 4
        if self.signal_dbm >= -67:
            return 3
        if self.signal_dbm >= -78:
            return 2
        if self.signal_dbm >= -88:
            return 1
        return 0


class WifiManager:
    def __init__(
        self,
        interface: str = DEFAULT_INTERFACE,
        conf_path: str = DEFAULT_CONF_PATH,
        service: str = DEFAULT_SERVICE,
        country: str | None = None,
    ):
        self.interface = interface
        self.conf_path = conf_path
        self.service = service
        # None = look up the optional config override; "" = no country=
        # line at all, so the radio runs the world regulatory domain and
        # adopts the router's advertised country (802.11d) — a hardcoded
        # country hides channels that are legal elsewhere (e.g. 5 GHz
        # 149-165: fine in the US/UK, absent from the German domain).
        if country is None:
            from ...config import ConfigManager

            country = ConfigManager.get_config().wifi_country
        self.country = country or ""

        self._wpa_cli_bin = _resolve_bin("wpa_cli", "/usr/sbin/wpa_cli", "/sbin/wpa_cli")
        self._systemctl_bin = _resolve_bin(
            "systemctl", "/usr/bin/systemctl", "/bin/systemctl"
        )
        self._networkctl_bin = _resolve_bin(
            "networkctl", "/usr/bin/networkctl", "/bin/networkctl"
        )
        self._supports_sae_cached: bool | None = None

    # ------------------------------------------------------------------
    # availability
    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        """True when this device can actually drive Wi-Fi (i.e. on the Pi)."""
        if self._wpa_cli_bin is None or self._systemctl_bin is None:
            return False
        return os.path.exists(f"/sys/class/net/{self.interface}")

    # ------------------------------------------------------------------
    # subprocess helpers
    # ------------------------------------------------------------------
    def _wpa_cli(self, *args: str, timeout: float = 5.0) -> str:
        out = subprocess.run(
            [self._wpa_cli_bin or "wpa_cli", "-i", self.interface, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return out.stdout

    # ------------------------------------------------------------------
    # scanning
    # ------------------------------------------------------------------
    def scan(self, settle: float = 2.5) -> list[Network]:
        """Trigger a scan and return nearby networks, strongest first.

        ``settle`` is how long we wait for the radio to populate results after
        asking it to scan. Safe to call repeatedly (rescan).
        """
        try:
            self._wpa_cli("scan")
            time.sleep(settle)
            results = self._wpa_cli("scan_results")
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"Wi-Fi scan failed: {e}")
            return []
        return self._parse_scan_results(results)

    @staticmethod
    def _decode_ssid(raw: str) -> str:
        """Decode wpa_supplicant's printf-escaped SSID into readable text.

        ``wpa_cli`` escapes every non-ASCII byte as ``\\xHH`` (so "Qiu’s
        Home" arrives as ``Qiu\\xe2\\x80\\x99s Home``), plus the single-char
        escapes in ``_WPA_ESCAPES``. Rebuild the raw bytes, then decode as
        UTF-8 — undecodable bytes become U+FFFD rather than failing, since
        an AP may broadcast arbitrary bytes. Control characters are also
        replaced with U+FFFD: an embedded NUL crashes pygame's renderer
        outright, and SSIDs are untrusted over-the-air data.
        """
        out = bytearray()
        i = 0
        while i < len(raw):
            ch = raw[i]
            if ch == "\\" and i + 1 < len(raw):
                nxt = raw[i + 1]
                if nxt == "x" and i + 3 < len(raw):
                    try:
                        out.append(int(raw[i + 2 : i + 4], 16))
                        i += 4
                        continue
                    except ValueError:
                        pass
                if nxt in _WPA_ESCAPES:
                    out.append(_WPA_ESCAPES[nxt])
                    i += 2
                    continue
            out.extend(ch.encode("utf-8"))
            i += 1
        decoded = out.decode("utf-8", errors="replace")
        return "".join(
            "�" if unicodedata.category(ch) == "Cc" else ch for ch in decoded
        )

    @classmethod
    def _parse_scan_results(cls, text: str) -> list[Network]:
        """Parse ``wpa_cli scan_results`` output.

        Columns are tab-separated: bssid / frequency / signal / flags / ssid.
        Hidden networks (blank SSID) are dropped; duplicates collapse to the
        strongest signal.
        """
        best: dict[str, Network] = {}
        for line in text.splitlines():
            parts = line.split("\t")
            if len(parts) < 5 or parts[0].lower().startswith("bssid"):
                continue
            try:
                signal = int(parts[2])
            except ValueError:
                continue
            flags = parts[3]
            ssid = cls._decode_ssid(parts[4].strip())
            if not ssid:
                continue
            secured = any(tag in flags for tag in ("WPA", "WEP", "PSK", "SAE"))
            existing = best.get(ssid)
            if existing is None or signal > existing.signal_dbm:
                best[ssid] = Network(ssid=ssid, secured=secured, signal_dbm=signal)
        return sorted(best.values(), key=lambda n: n.signal_dbm, reverse=True)

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------
    def status(self) -> dict[str, str]:
        try:
            return self._parse_status(self._wpa_cli("status"))
        except (subprocess.SubprocessError, OSError) as e:
            logger.error(f"Wi-Fi status failed: {e}")
            return {}

    @staticmethod
    def _parse_status(text: str) -> dict[str, str]:
        status: dict[str, str] = {}
        for line in text.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                status[key.strip()] = value.strip()
        return status

    def supports_sae(self) -> bool:
        """True when the running wpa_supplicant was built with WPA3/SAE.

        Probed via ``wpa_cli get_capability key_mgmt`` and cached: the answer
        is a build-time property of the image's supplicant. Gates the modern
        network block — writing ``sae_password``/``ieee80211w`` to a
        supplicant compiled without CONFIG_SAE/CONFIG_IEEE80211W is a config
        parse error that would take Wi-Fi down entirely (relevant when new
        app bytecode lands on an older dev image)."""
        if self._supports_sae_cached is None:
            try:
                caps = self._wpa_cli("get_capability", "key_mgmt")
            except (subprocess.SubprocessError, OSError):
                return False  # transient failure: fall back, don't cache
            self._supports_sae_cached = "SAE" in caps.split()
        return self._supports_sae_cached

    def is_associated(self) -> bool:
        """True when wpa_supplicant has completed association, regardless of DHCP state.

        Use this for the boot gate: DHCP may still be in flight at startup, but
        association alone is enough to know the user already has credentials.
        """
        return self.status().get("wpa_state") == "COMPLETED"

    def wait_for_association(self, timeout: float = 10.0, poll: float = 0.5) -> bool:
        """Block until wpa_supplicant reaches COMPLETED state, or timeout expires.

        Polls is_associated() every ``poll`` seconds. This runs before the main
        pygame loop so it does not block the UI. Returns immediately if already
        associated.
        """
        if self.is_associated():
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(poll)
            if self.is_associated():
                return True
        return False

    def ipv4_address(self) -> str | None:
        """The interface's IPv4 address straight from the kernel (SIOCGIFADDR).

        ``wpa_cli status`` reports ``ip_address=`` only while the supplicant
        holds an l2_packet socket it can read one from; asking the kernel
        keeps lease detection independent of supplicant build/driver details
        (and gives us the address itself for the log). A link-local 169.254
        address is an autoconfiguration fallback, not a lease, so it counts
        as "no address". Returns None when the interface has none — or does
        not exist, as on dev machines.
        """
        # Deferred imports: fcntl is Linux/Unix-only and this path only ever
        # runs on the appliance.
        import fcntl
        import socket
        import struct

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            packed = fcntl.ioctl(
                s.fileno(),
                0x8915,  # SIOCGIFADDR
                struct.pack("256s", self.interface.encode()[:15]),
            )
            address = socket.inet_ntoa(packed[20:24])
        except OSError:
            return None
        finally:
            s.close()
        return None if address.startswith("169.254.") else address

    def link_state(self) -> str:
        """networkd's ``<operational>/<setup>`` state for the interface.

        Diagnostic only, and the only window into networkd a release image
        has (no SSH): "routable/configured" is a working link, while
        "carrier/configuring" says DHCP is still in flight and
        "no-carrier/..." says the radio never associated. Empty string when
        networkctl is unavailable or the call fails.
        """
        if self._networkctl_bin is None:
            return ""
        try:
            out = subprocess.run(
                [self._networkctl_bin, "list", "--no-legend", self.interface],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            return ""
        # "IDX LINK TYPE OPERATIONAL SETUP", optionally with a leading "*"
        # marker on the default-route link — read from the right instead.
        parts = out.stdout.split()
        return f"{parts[-2]}/{parts[-1]}" if len(parts) >= 5 else ""

    def _identity_files(self) -> str:
        """State of the files networkd needs to build a DHCP client id.

        An empty or absent machine-id, or a missing udev database entry for
        the interface, makes the DUID/IAID unavailable and the DHCPv4
        client fails to start with ENOENT.
        """
        lines = []
        paths = [
            "/etc/machine-id",
            "/run/machine-id",
            f"/sys/class/net/{self.interface}/ifindex",
        ]
        for path in paths:
            try:
                size = os.stat(path).st_size
                lines.append(f"{path}: {size} bytes")
            except OSError as e:
                lines.append(f"{path}: {e.strerror}")
        try:
            with open(f"/sys/class/net/{self.interface}/ifindex") as f:
                index = f.read().strip()
            udev = f"/run/udev/data/n{index}"
            lines.append(f"{udev}: {'present' if os.path.exists(udev) else 'MISSING'}")
        except OSError as e:
            lines.append(f"udev db entry: unavailable ({e.strerror})")
        return "\n".join(lines)

    def diagnostics(self) -> str:
        """networkd's own account of the link, for the debug log.

        Its reasoning lives in the journal, which is volatile — so when a
        lease fails, copy the relevant part into our own log rather than
        leaving it to expire. Best-effort; returns whatever could be
        collected.
        """
        out = [f"--- DHCP client identity inputs ---\n{self._identity_files()}"]
        commands = [
            ["journalctl", "-u", "systemd-networkd", "-n", "60", "--no-pager"],
            ["journalctl", "-u", f"wpa_supplicant@{self.interface}", "-n", "30",
             "--no-pager"],
        ]
        if self._networkctl_bin:
            commands.insert(
                0, [self._networkctl_bin, "status", "--no-pager", self.interface]
            )
        for cmd in commands:
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=10, check=False
                )
                body = (result.stdout or result.stderr).strip()
            except (subprocess.SubprocessError, OSError) as e:
                body = f"<{e}>"
            out.append(f"--- {' '.join(cmd)} ---\n{body}")
        return "\n".join(out)

    def request_dhcp(self) -> None:
        """Ask systemd-networkd to (re)run link configuration now.

        In the provisioning flow association happens long after boot, and a
        DHCP client that saw no carrier at boot — or is sitting in a retry
        backoff after an earlier failure — may not lease promptly on its own.
        ``networkctl reconfigure`` re-applies the .network config and
        restarts the DHCP client; ``renew`` is the fallback for systemd
        versions without it. Best-effort: failure only means we fall back to
        networkd's own schedule.
        """
        if self._networkctl_bin is None:
            return
        for verb in ("reconfigure", "renew"):
            try:
                result = subprocess.run(
                    [self._networkctl_bin, verb, self.interface],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            except (subprocess.SubprocessError, OSError) as e:
                logger.warning(f"networkctl {verb} {self.interface} failed: {e}")
                return
            if result.returncode == 0:
                return
            logger.warning(
                f"networkctl {verb} {self.interface} returned "
                f"{result.returncode}: {result.stderr.strip()}"
            )

    def is_connected(self) -> bool:
        """Associated *and* has an IP lease (so the network is actually usable)."""
        status = self.status()
        if status.get("wpa_state") != "COMPLETED":
            return False
        return bool(status.get("ip_address")) or self.ipv4_address() is not None

    def current_ssid(self) -> str | None:
        # ``wpa_cli status`` escapes the ssid the same way scan results are;
        # decode so the connected-network checkmark matches the scan list.
        raw = self.status().get("ssid")
        return self._decode_ssid(raw) if raw else None

    # ------------------------------------------------------------------
    # connecting
    # ------------------------------------------------------------------
    def connect(self, ssid: str, psk: str | None) -> None:
        """Persist credentials and (re)join the network.

        ``psk`` may be None/empty for an open network. Raises on failure to
        write the config or restart the service; association success must be
        confirmed separately via :meth:`wait_for_connection`.
        """
        self._write_config(ssid, psk, sae=bool(psk) and self.supports_sae())
        # Prefer wpa_cli reconfigure over a full service restart: reconfigure
        # reloads the config in-place while preserving wpa_supplicant's BSSID
        # blacklist. A full restart resets that state, so on routers with
        # multiple BSSIDs (dual-band APs) wpa_supplicant redundantly hammers
        # a failing BSSID from scratch on every attempt, blowing the 25-second
        # connection window. reconfigure lets the blacklist accumulate across
        # retries so bad BSSIDs are skipped on the next attempt. Fall back to
        # a restart only when wpa_supplicant isn't running at all.
        reconfigure_ok = False
        try:
            result = subprocess.run(
                [self._wpa_cli_bin or "wpa_cli", "-i", self.interface, "reconfigure"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            reconfigure_ok = result.returncode == 0 and "OK" in result.stdout
        except (subprocess.SubprocessError, OSError):
            pass

        if not reconfigure_ok:
            try:
                subprocess.run(
                    [self._systemctl_bin or "systemctl", "restart", self.service],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                raise RuntimeError(
                    f"Failed to restart {self.service}: {e.stderr or e}"
                ) from e

    def wait_for_connection(self, timeout: float = 60.0, poll: float = 1.0) -> bool:
        """Poll until associated with an IP, or ``timeout`` seconds elapse."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_connected():
                return True
            time.sleep(poll)
        return self.is_connected()

    def _write_config(self, ssid: str, psk: str | None, sae: bool = False) -> None:
        content = self._build_config(ssid, psk, self.country, sae=sae)
        directory = os.path.dirname(self.conf_path) or "."
        os.makedirs(directory, exist_ok=True)
        # Atomic replace so a crash mid-write can't leave a truncated config
        # that would brick Wi-Fi on the next boot.
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".wpa_supplicant-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.conf_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _escape(value: str) -> str:
        """Escape a value for a wpa_supplicant double-quoted string."""
        return value.replace("\\", "\\\\").replace('"', '\\"')

    @staticmethod
    def _hash_psk(ssid: str, psk: str) -> str:
        """Derive the 256-bit PSK hex string from SSID + passphrase.

        Uses PBKDF2-HMAC-SHA1 with 4096 iterations — identical to the
        ``wpa_passphrase`` tool. The resulting 64-char hex string is written
        without quotes so wpa_supplicant treats it as a raw PSK rather than
        a plaintext passphrase, keeping credentials off the filesystem.
        """
        import hashlib
        return hashlib.pbkdf2_hmac("sha1", psk.encode(), ssid.encode(), 4096, 32).hex()

    @classmethod
    def _build_config(
        cls, ssid: str, psk: str | None, country: str, sae: bool = False
    ) -> str:
        """Render the wpa_supplicant config for one network.

        ``sae`` additionally offers WPA3/SAE, which is used whenever the
        running supplicant supports it: wpa_supplicant then negotiates the
        strongest protocol the access point actually offers, so a WPA3 or
        transition network is joined with SAE and a WPA2-only one with
        WPA-PSK. Without it the block is plain hashed-PSK.
        """
        lines = [
            "ctrl_interface=/run/wpa_supplicant",
            "update_config=1",
        ]
        if country:
            lines.append(f"country={country}")
        lines += [
            "",
            "network={",
            f'    ssid="{cls._escape(ssid)}"',
        ]
        if psk and sae:
            # Offer both, strongest first from wpa_supplicant's point of
            # view: it picks SAE on a WPA3 or transition AP and WPA-PSK on
            # a WPA2-only one. SAE authenticates with the raw passphrase by
            # protocol design, so sae_password is plaintext (the file is
            # 0600 on /data); the hashed psk serves the WPA-PSK path.
            # ieee80211w=1 advertises PMF as available, which is what a
            # transition-capable client wants — SAE brings PMF with it and
            # a WPA2-only AP is unaffected.
            lines.append(f"    psk={cls._hash_psk(ssid, psk)}")
            lines.append(f'    sae_password="{cls._escape(psk)}"')
            lines.append("    key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE")
            lines.append("    ieee80211w=1")
        elif psk:
            lines.append(f"    psk={cls._hash_psk(ssid, psk)}")
            lines.append("    key_mgmt=WPA-PSK")
        else:
            lines.append("    key_mgmt=NONE")
        lines.append("}")
        lines.append("")
        return "\n".join(lines)
