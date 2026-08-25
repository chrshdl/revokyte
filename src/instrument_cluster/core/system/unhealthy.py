"""Image-attributable faults, published where the OTA health check can see them.

`ota-health-check.sh` gates `rauc status mark-good`. It verifies the hardware a
driver/kernel regression would silently break; this module is the app's side of
the same contract, so a fault baked into the *image* also withholds mark-good
and lets U-Boot rotate back to the previous slot.

**What belongs here.** Only conditions a rollback would actually fix: a view
that cannot build, a missing bundled asset. Never environmental ones — no
network, no telemetry, no game running. That is the same line `check_wifi`
draws when it requires the interface to exist but deliberately not to be
associated: a device at the track may have no known network, and no rollback
cures that. Writing the marker for a transient condition withholds mark-good
for something rolling back cannot repair.

**Why /run.** It is tmpfs, so the marker cannot outlive the boot. On /data a
single transient failure would poison every subsequent boot into permanent
rollback. `clear()` on startup narrows it further, to the current app run — a
restart that succeeds should not inherit the previous one's verdict.

The file is a plain list of reasons, one per line. The health check only tests
whether it is non-empty, so new fault types need no change there.
"""

from __future__ import annotations

import os

from ...logger import Logger

MARKER = "/run/instrument-cluster/unhealthy"

_logger = Logger("unhealthy").get()


def clear(path: str | None = None) -> None:
    """Drop any marker from an earlier run of the app in this boot."""
    path = path or MARKER
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        _logger.warning("Could not clear the health marker: %s", e)


def report(reason: str, path: str | None = None) -> None:
    """Record one image-attributable fault. Best effort by design.

    Never raises: this runs on the startup path, and failing to *report* a
    degraded image must not be what takes the dashboard down. A dev machine
    with no /run/instrument-cluster simply logs.
    """
    # Resolved per call, not as a default argument: a default would bind the
    # module-level value at import and silently ignore any later override.
    path = path or MARKER
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(f"{reason}\n")
    except OSError as e:
        _logger.warning("Could not write the health marker (%s): %s", reason, e)
    _logger.error("Image-attributable fault: %s", reason)


def reasons(path: str | None = None) -> list[str]:
    """What this run has reported, for tests and diagnostics."""
    path = path or MARKER
    try:
        with open(path) as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []
