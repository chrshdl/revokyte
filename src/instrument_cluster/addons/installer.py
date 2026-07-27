from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .artifact_verify import flatten_extract, sha256_file, verify_signature
from .feeds import ACTIVE_LINK, FeedDescriptor

# Re-exported for callers/tests that reach them via this module.
_flatten_extract = flatten_extract
__all__ = ["FeedUnreachable", "InstallResult", "install_from_url",
           "resolve_latest_tarball_url", "verify_signature"]


class FeedUnreachable(Exception):
    """The release API could not be reached at all (no network, DNS, TLS).

    Separate from "no matching asset in the release" so the UI can tell the
    user their device is offline instead of claiming the feed has no
    release — the two need completely different fixes, and on a release
    image with no SSH the on-screen message is the only diagnosis available.
    """

ENV_FILE = Path("/data/etc/instrument-cluster-proxy")
WRAPPER_NAME = "proxy-wrapper.py"
SYSTEMCTL: str | None = shutil.which("systemctl")

ASSET_SUFFIX = ".tar.gz"


def resolve_latest_tarball_url(descriptor: FeedDescriptor) -> str | None:
    """Return the download URL of the feed's latest self-contained tarball.

    We always install the *latest* published release rather than a hardcoded
    version: the device asks the descriptor's GitHub Releases API which release
    is newest and picks its ``<asset_prefix><ver>.tar.gz`` asset (the .sha256 and
    .sig sidecars, verified in install_from_url, sit next to it). Returns None
    when the release carries no matching asset, so callers fail closed instead
    of installing something unexpected, and raises :class:`FeedUnreachable`
    when the API could not be reached at all.
    """
    api_url = f"https://api.github.com/repos/{descriptor.github_repo}/releases/latest"
    req = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "instrument-cluster-installer",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.load(response)
    except Exception as e:
        raise FeedUnreachable(str(e) or e.__class__.__name__) from e

    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if name.startswith(descriptor.asset_prefix) and name.endswith(ASSET_SUFFIX):
            url = asset.get("browser_download_url")
            if url:
                return url
    return None


@dataclass
class InstallResult:
    ok: bool
    message: str = ""


def fetch_expected_sha256(sidecar_url: str) -> str | None:
    """Fetch the ``.sha256`` sidecar and return the bare hex digest, or None.

    The sidecar is in ``sha256sum`` format (``<hash>  <filename>``); a bare
    hash is also tolerated.
    """
    try:
        with urllib.request.urlopen(sidecar_url, timeout=30) as response:
            text = response.read().decode("utf-8", "replace").strip()
    except Exception:
        return None
    return text.split()[0] if text else None


def fetch_signature(sig_url: str) -> bytes | None:
    """Fetch the detached ``.sig`` sidecar (raw Ed25519 signature), or None."""
    try:
        with urllib.request.urlopen(sig_url, timeout=30) as response:
            return response.read()
    except Exception:
        return None


def install_from_url(
    url: str,
    descriptor: FeedDescriptor,
    ip: str,
    sha256: str | None = None,
) -> InstallResult:
    if not ip:
        return InstallResult(False, "IP address missing")

    # Each feed installs into its own subdirectory; the active-feed symlink
    # (updated at the end) selects which one the proxy service runs.
    dest = Path(descriptor.install_dir)

    try:
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return InstallResult(False, f"Could not prepare {dest}: {e}")

    fd, tmp_path = tempfile.mkstemp(prefix="feed-installer-", suffix=".tar.gz")
    os.close(fd)
    tmp_tar = Path(tmp_path)

    try:
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                with open(tmp_tar, "wb") as out_file:
                    shutil.copyfileobj(response, out_file)
        except Exception as e:
            return InstallResult(False, f"Download failed: {e}")

        # Verify the download. Use the caller-pinned digest if given, otherwise
        # fetch the expected checksum from the published sidecar. Fail closed:
        # never install an unverified tarball.
        expected = sha256 or fetch_expected_sha256(url + ".sha256")
        if not expected:
            return InstallResult(False, "Could not obtain expected sha256 checksum")

        if sha256_file(tmp_tar) != expected.lower():
            return InstallResult(False, "SHA256 mismatch")

        # Verify authenticity: the tarball must carry a valid Ed25519 signature
        # from our release key. Fail closed if the signature is missing or bad.
        signature = fetch_signature(url + ".sig")
        if signature is None:
            return InstallResult(False, "Could not fetch release signature")
        with open(tmp_tar, "rb") as f:
            if not verify_signature(f.read(), signature, descriptor.signing_pubkey_b64):
                return InstallResult(False, "Signature verification failed")

        # NOTE: this deletes this feed's previous version files (its own
        # subdirectory only — a different feed's install is left untouched).
        for child in dest.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

        try:
            with tarfile.open(tmp_tar, "r:*") as tar:
                flatten_extract(tar, dest)
        except Exception as e:
            return InstallResult(False, f"Extraction failed: {e}")

        wrapper_path = dest / WRAPPER_NAME
        if not wrapper_path.exists():
            return InstallResult(False, f"Critical: {WRAPPER_NAME} not found in {dest}")

        wrapper_path.chmod(0o755)

    finally:
        if tmp_tar.exists():
            tmp_tar.unlink()

    # Point the active-feed symlink at the feed we just installed, so the static
    # systemd service (which runs <base>/active/proxy-wrapper.py) picks it up.
    active_link = Path(ACTIVE_LINK)
    try:
        if active_link.is_symlink() or active_link.exists():
            active_link.unlink()
        active_link.symlink_to(dest)
    except OSError as e:
        return InstallResult(False, f"Failed to set active feed {active_link}: {e}")

    config_content = descriptor.env_content(ip)

    try:
        ENV_FILE.write_text(config_content, encoding="utf-8")
        ENV_FILE.chmod(0o644)
    except Exception as e:
        return InstallResult(False, f"Failed to write config {ENV_FILE}: {e}")

    if SYSTEMCTL:
        print("Restarting service...")
        subprocess.run(
            [SYSTEMCTL, "restart", "instrument-cluster-proxy.service"], check=False
        )

    return InstallResult(True, "Installation completed successfully.")
