from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .artifact_verify import flatten_extract, sha256_file, verify_signature
from .feeds import ACTIVE_LINK, FeedDescriptor

# Re-exported for callers/tests that reach them via this module.
_flatten_extract = flatten_extract
__all__ = ["FeedRateLimited", "FeedUnreachable", "FeedVersionMissing",
           "InstallResult", "install_from_url", "installed_feed_ip",
           "resolve_pinned_agent_url", "resolve_pinned_tarball_url",
           "verify_signature"]


class FeedUnreachable(Exception):
    """The release API could not be reached at all (no network, DNS, TLS).

    Separate from "no matching asset in the release" so the UI can tell the
    user their device is offline instead of claiming the feed has no
    release — the two need completely different fixes, and on a release
    image with no SSH the on-screen message is the only diagnosis available.
    """


class FeedVersionMissing(Exception):
    """The release the descriptor pins does not exist on GitHub.

    Not a FeedUnreachable: the network is fine and the answer was
    authoritative. This is a packaging fault — a retracted or mistyped tag —
    so it needs a message that sends someone to the image, not the router.
    """


class FeedRateLimited(FeedUnreachable):
    """GitHub answered, but refused the request as rate-limited.

    A subclass so existing handling still catches it, but distinguishable:
    the device is demonstrably online, and telling its owner "no network
    connection" sends them to rewire a working router. Unauthenticated API
    calls share a 60/hour budget per public IP, so this is reachable in a
    household behind CGNAT or after a few retries.
    """

ENV_FILE = Path("/data/etc/instrument-cluster-proxy")
WRAPPER_NAME = "proxy-wrapper.py"
SYSTEMCTL: str | None = shutil.which("systemctl")

ASSET_SUFFIX = ".tar.gz"


def resolve_pinned_tarball_url(descriptor: FeedDescriptor) -> str | None:
    """Return the download URL of the feed's pinned self-contained tarball.

    The device installs the release the descriptor *pins*, not whatever is
    newest. The feed and the cluster share the ``TelemetryFrame`` schema, so a
    feed published after this image was built can speak a shape this image
    does not — the exact failure the ``received_time`` stamping fixed, only
    arriving silently on someone else's schedule. Pinning also makes the
    install reproducible and matches the desktop path, where the same feeds
    are pinned as git refs in pyproject's ``pc`` extra.

    Picks the release's ``<asset_prefix><ver>.tar.gz`` asset (the .sha256 and
    .sig sidecars, verified in install_from_url, sit next to it). Returns None
    when the release carries no matching asset, so callers fail closed instead
    of installing something unexpected, and raises :class:`FeedUnreachable`
    when the API could not be reached at all.
    """
    return _pick_asset(_fetch_release(descriptor), descriptor.asset_prefix,
                       ASSET_SUFFIX)


def _fetch_release(descriptor: FeedDescriptor) -> dict:
    """The pinned release's GitHub API payload, with the error taxonomy the UI
    relies on to tell "offline" apart from "packaging mistake"."""
    api_url = (
        f"https://api.github.com/repos/{descriptor.github_repo}"
        f"/releases/tags/{descriptor.version}"
    )
    req = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "instrument-cluster-installer",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        # A reply — even a refusal — proves the link works, so never report
        # these as "no network".
        if e.code in (403, 429):
            raise FeedRateLimited(f"HTTP {e.code}") from e
        if e.code == 404:
            # The pinned tag isn't published (retracted, renamed, typo in the
            # descriptor). Distinct from "no network" and from "no matching
            # asset" — this one is a packaging mistake, not the user's.
            raise FeedVersionMissing(
                f"{descriptor.github_repo} has no release tagged "
                f"{descriptor.version}"
            ) from e
        raise FeedUnreachable(f"HTTP {e.code}") from e
    except Exception as e:
        raise FeedUnreachable(str(e) or e.__class__.__name__) from e


def _pick_asset(release: dict, prefix: str, suffix: str) -> str | None:
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith(prefix) and name.endswith(suffix):
            url = asset.get("browser_download_url")
            if url:
                return url
    return None


def resolve_pinned_agent_url(descriptor: FeedDescriptor) -> str | None:
    """Download URL of the feed's pinned PC-agent asset, or None.

    The agent ships in the *same* pinned release as the proxy tarball, so the
    two halves of a feed can never be a version apart. That matters more here
    than usual: the agent produces frames directly, so a mismatched one would
    speak a TelemetryFrame shape this image was never tested against.
    """
    if descriptor.agent is None:
        return None
    release = _fetch_release(descriptor)
    return _pick_asset(
        release, descriptor.agent.asset_prefix, descriptor.agent.asset_suffix
    )


def installed_feed_ip() -> str:
    """The console address the installed feed is already configured with.

    Every descriptor's env file carries it under its own key (``GT_PS_IP``,
    ``ACC_PC_IP``, ...), so this matches on the shared ``_IP`` suffix rather
    than knowing any particular feed. It is the authoritative record — it is
    literally what the running proxy connects to — which is what lets an
    update re-install without asking for anything.

    Returns "" when there is no env file or no address in it.
    """
    try:
        text = ENV_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""

    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip().endswith("_IP"):
            return value.strip()
    return ""


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
