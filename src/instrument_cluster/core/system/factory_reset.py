"""Factory reset: erase user data from the appliance and reboot.

This exists so a user can hand the device on, return it, or dispose of it
without leaving personal data behind (Wi-Fi credentials, the console/PC IP
addresses they entered, an installed feed). It is deliberately a *data*
reset, not a firmware reset: the OS image, the A/B slots and the RAUC state
are system-level and untouched, so the device still boots and updates.

The reset is best-effort per target — one unreadable path must never abort
the rest — and every target is logged. On the appliance it ends with a
reboot so the device comes up in the first-boot state (Wi-Fi setup screen,
default settings). Off the appliance (dev machine) nothing is deleted from
the system and no reboot is issued; only the app's own config file is
cleared, which keeps the function safe to exercise and test anywhere.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ...logger import Logger
from ...peripherals.display import is_raspberry_pi

logger = Logger("factory_reset").get()

# Persistent data partition on the appliance. Everything the user can create
# at runtime lives under here; the read-only rootfs is never touched.
DATA_ROOT = Path("/data")

# The header-only wpa_supplicant config the OS image seeds on a pristine
# device (prepare-data-dirs.service). Restoring the credentials file to
# exactly this makes WifiManager.has_credentials() report "unprovisioned",
# so the next boot pushes the on-screen Wi-Fi setup — the true first-boot
# state. Deleting the file outright would also work, but re-seeding keeps
# the 0600 file present and owned by us.
_WPA_CONF = DATA_ROOT / "etc" / "wpa_supplicant" / "wpa_supplicant-wlan0.conf"
_WPA_SEED = "ctrl_interface=/run/wpa_supplicant\nupdate_config=1\n"


def _personal_data_targets(config_path: Path, data_root: Path) -> list[Path]:
    """Files/dirs holding user-created or personal data, to be removed.

    Kept out of the list on purpose: ``machine-id`` (device identity, not
    personal in this build), the RAUC status dir and the A/B system state
    (needed to keep updating), and the Mesa shader cache (not personal;
    regenerated on next run).
    """
    return [
        # App config: brightness, feed selection, and — personal — the
        # console/PC IP addresses (direct_host, recent_connected).
        config_path,
        # Installed telemetry feed + its env file (holds the game PC's IP).
        data_root / "opt" / "telemetry",
        data_root / "etc" / "instrument-cluster-proxy",
        # User-dropped external plugins.
        data_root / "plugins",
    ]


def _remove(path: Path) -> None:
    """Delete a file or directory tree; log the outcome, never raise."""
    try:
        if path.is_symlink() or path.is_file():
            path.unlink()
            logger.info("factory reset: removed file %s", path)
        elif path.is_dir():
            shutil.rmtree(path)
            logger.info("factory reset: removed dir %s", path)
        else:
            logger.debug("factory reset: nothing to remove at %s", path)
    except OSError:
        logger.exception("factory reset: could not remove %s", path)


def _reseed_wifi(conf_path: Path) -> None:
    """Reset Wi-Fi credentials to the header-only seed (0600)."""
    try:
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        conf_path.write_text(_WPA_SEED, encoding="utf-8")
        os.chmod(conf_path, 0o600)
        logger.info("factory reset: re-seeded Wi-Fi config at %s", conf_path)
    except OSError:
        logger.exception("factory reset: could not re-seed Wi-Fi config")


def _reboot() -> None:
    """Reboot the appliance so it comes up in the first-boot state."""
    binary = shutil.which("systemctl") or "/usr/bin/systemctl"
    try:
        logger.info("factory reset: rebooting via %s reboot", binary)
        subprocess.run([binary, "reboot"], timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        logger.exception("factory reset: reboot command failed")


def perform_factory_reset(
    *,
    config_path: Path | None = None,
    data_root: Path = DATA_ROOT,
    wifi_conf_path: Path = _WPA_CONF,
    reboot: bool | None = None,
) -> None:
    """Erase user data and (on the appliance) reboot.

    Args are injectable for tests; production calls take the defaults. When
    ``reboot`` is None it is decided by :func:`is_raspberry_pi` — the device
    reboots, a dev machine does not.
    """
    if config_path is None:
        # Import here to avoid a module-level import cycle (config imports
        # from the logger which imports … keep the top of the module thin).
        from ...config import ConfigManager

        config_path = ConfigManager.path

    logger.warning("factory reset: erasing user data")

    for target in _personal_data_targets(Path(config_path), Path(data_root)):
        _remove(target)

    _reseed_wifi(Path(wifi_conf_path))

    if reboot is None:
        reboot = is_raspberry_pi()

    if reboot:
        _reboot()
    else:
        logger.info("factory reset: not on the appliance — skipping reboot")
