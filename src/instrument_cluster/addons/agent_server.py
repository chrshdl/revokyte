"""Hand a feed's PC agent to the user's gaming PC over the LAN.

The appliance cannot install anything onto the game PC, so it does the next best
thing: it fetches the signed agent bundle, writes its own address into the
bundle's config, and serves it on the local network for as long as the pairing
screen is open. The user types one URL on the PC and gets a download that is
already pointed back here — no IP to copy, no config to edit.

Serving only while that screen is open is deliberate. This is a pairing window,
not a service: nothing listens once the user walks away from it.
"""

from __future__ import annotations

import html
import io
import shutil
import socket
import tempfile
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..logger import Logger
from .artifact_verify import sha256_file, verify_signature
from .feeds import FeedDescriptor
from .installer import (
    FeedUnreachable,
    fetch_expected_sha256,
    fetch_signature,
    resolve_pinned_agent_url,
)

LOGGER = Logger("agent-server").get()

# Where the agent should send frames. Same sink the installed proxies use.
JSONL_PORT = 5600
CONFIG_NAME = "config.json"


@dataclass
class AgentBundle:
    path: Path
    filename: str
    sha256: str
    # False when the release carried no .sig sidecar to check. Carried all the
    # way to the download page, because the person who needs to know is the one
    # about to run a .bat on their gaming PC.
    verified: bool = True


class AgentUnavailable(Exception):
    """The bundle could not be fetched or did not verify."""


def prepare_bundle(descriptor: FeedDescriptor, cluster_ip: str) -> AgentBundle:
    """Download, verify, and personalise the agent zip.

    The pinned release is the only source. There is deliberately no way to point
    this at a local file: the server hands a Windows executable to another
    machine under the appliance's own name, which is a good thing to be trusted
    for and a bad thing to lend out. Testing an unreleased agent means tagging a
    prerelease — you then test what you would ship.

    Verification is the same chain the proxy installer uses — pinned release,
    ``.sha256`` sidecar, detached Ed25519 signature against the descriptor's
    public key — and it happens *before* the config rewrite, so what we check is
    exactly what CI signed. The rewrite necessarily breaks that signature, which
    is why the served file is accompanied by its pre-rewrite digest rather than
    the signature itself.
    """
    if descriptor.agent is None:
        raise AgentUnavailable(f"{descriptor.label} has no PC agent")

    try:
        url = resolve_pinned_agent_url(descriptor)
    except FeedUnreachable as e:
        raise AgentUnavailable(f"Could not reach the release: {e}") from e
    if not url:
        raise AgentUnavailable(
            f"{descriptor.version} has no {descriptor.agent.asset_prefix}* asset"
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="agent-bundle-"))
    filename = url.rsplit("/", 1)[-1]
    downloaded = tmp_dir / filename
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            with open(downloaded, "wb") as out:
                shutil.copyfileobj(response, out)
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise AgentUnavailable(f"Download failed: {e}") from e

    digest = sha256_file(downloaded)
    expected = fetch_expected_sha256(url + ".sha256")
    if expected and digest != expected:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise AgentUnavailable("Checksum mismatch")

    signature = fetch_signature(url + ".sig")
    verified = signature is not None
    if verified:
        if not verify_signature(
            downloaded.read_bytes(), signature, descriptor.signing_pubkey_b64
        ):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise AgentUnavailable("Signature verification failed")
    else:
        # A release built before the signing key was configured. Still served —
        # refusing would strand those images — but the person about to run it
        # gets told, on the screen and on the download page.
        LOGGER.warning(
            "no .sig sidecar for %s — serving UNVERIFIED. This hands an "
            "unsigned executable to the game PC.", filename,
        )

    _write_config(downloaded, cluster_ip, _mdns_name())
    return AgentBundle(
        path=downloaded, filename=filename, sha256=digest, verified=verified
    )


def _mdns_name() -> str | None:
    """This appliance's mDNS name, e.g. ``instrument-cluster.local``.

    Written into the served config as the *preferred* sink address: the
    appliance's DHCP lease drifts, and an IP baked in at download time then
    silently sends telemetry nowhere. The name keeps following the appliance
    (Windows 10+ resolves .local natively); the IP stays in ``output`` as the
    agent's fallback for networks that block multicast.
    """
    name = socket.gethostname().split(".")[0].strip()
    return f"{name}.local" if name else None


def _write_config(zip_path: Path, cluster_ip: str,
                  mdns_name: str | None = None) -> None:
    """Point the bundle's ``config.json`` at this appliance.

    ``output`` stays the literal IP — agents released before ``output_mdns``
    existed use it verbatim, and handing those a hostname would put a
    blocking resolve in their send path. Newer agents prefer the added
    ``output_mdns`` line and fall back to the IP on their own.

    Rewrites in place by copying the archive: a zip entry cannot be replaced
    without rebuilding, and the bundles are small enough that it does not
    matter.
    """
    target = f'"output": "udp://{cluster_ip}:{JSONL_PORT}"'
    mdns_target = (
        f'"output_mdns": "udp://{mdns_name}:{JSONL_PORT}"' if mdns_name else None
    )
    with zipfile.ZipFile(zip_path) as source:
        entries = source.infolist()
        config_entries = [e for e in entries if e.filename.endswith(CONFIG_NAME)]
        if not config_entries:
            LOGGER.warning("bundle has no %s; serving it unmodified", CONFIG_NAME)
            return
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
            for entry in entries:
                data = source.read(entry.filename)
                if entry in config_entries:
                    text = data.decode("utf-8")
                    # The output lines are the only ones to touch; the rest
                    # of the file is the agent's own defaults.
                    data = _replace_output(text, target, mdns_target)
                    data = data.encode("utf-8")
                out.writestr(entry, data)
    zip_path.write_bytes(buffer.getvalue())


def _replace_output(text: str, target: str,
                    mdns_target: str | None = None) -> str:
    lines = []
    for line in text.splitlines():
        if '"output_mdns"' in line:
            continue  # superseded by ours, or dropped when we have none
        if '"output"' in line:
            indent = line[: len(line) - len(line.lstrip())]
            trailing = "," if line.rstrip().endswith(",") else ""
            if mdns_target:
                # The comma juggling keeps the file valid JSON whether the
                # output line was mid-object or the last key.
                lines.append(f"{indent}{target},")
                lines.append(f"{indent}{mdns_target}{trailing}")
            else:
                lines.append(f"{indent}{target}{trailing}")
        else:
            lines.append(line)
    return "\n".join(lines) + "\n"


class AgentHandoffServer:
    """Serves one bundle on the LAN for the life of the pairing screen."""

    def __init__(self, bundle: AgentBundle, descriptor: FeedDescriptor, port: int):
        self._bundle = bundle
        self._descriptor = descriptor
        self._port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.downloads = 0

    def start(self) -> None:
        handler = _make_handler(self)
        # 0.0.0.0: the whole point is to be reachable from the gaming PC.
        self._httpd = ThreadingHTTPServer(("0.0.0.0", self._port), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="agent-handoff", daemon=True
        )
        self._thread.start()
        LOGGER.info("serving %s on :%d", self._bundle.filename, self._port)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        shutil.rmtree(self._bundle.path.parent, ignore_errors=True)
        LOGGER.info("pairing window closed")


def _make_handler(server: AgentHandoffServer):
    bundle = server._bundle
    descriptor = server._descriptor

    class Handler(BaseHTTPRequestHandler):
        # BaseHTTPRequestHandler logs every hit to stderr; route it to the app
        # logger instead of the console the appliance does not have.
        def log_message(self, fmt: str, *args: object) -> None:
            LOGGER.info("%s - %s", self.address_string(), fmt % args)

        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            if self.path.rstrip("/") in ("", "/index.html"):
                self._send_page()
            elif self.path.lstrip("/") == bundle.filename:
                self._send_bundle()
            else:
                self.send_error(404)

        def _send_page(self) -> None:
            body = _PAGE.format(
                label=html.escape(descriptor.label),
                unlocks=html.escape(descriptor.agent.unlocks),
                filename=html.escape(bundle.filename),
                sha256=bundle.sha256,
                version=html.escape(descriptor.version),
                warning="" if bundle.verified else _UNVERIFIED_BANNER,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_bundle(self) -> None:
            data = bundle.path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header(
                "Content-Disposition", f'attachment; filename="{bundle.filename}"'
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            server.downloads += 1

    return Handler


# Shown in place of nothing when the served bundle carries no valid signature.
# Not escaped/formatted with user input — it is a constant.
_UNVERIFIED_BANNER = (
    '<p class="warn"><strong>Unverified build.</strong> This file was supplied '
    "locally to the cluster and is not signed by the project's release key. "
    "It contains a program you are about to run on this PC. Do not continue "
    "unless you built it yourself or you know exactly who did.</p>"
)

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{label} telemetry agent</title>
<style>
 body {{ font-family: system-ui, sans-serif; max-width: 34rem; margin: 4rem auto;
        padding: 0 1.5rem; line-height: 1.6; color: #111; }}
 a.btn {{ display: inline-block; background: #111; color: #fff; padding: .8rem 1.4rem;
        border-radius: .4rem; text-decoration: none; font-weight: 600; }}
 code {{ background: #f2f2f2; padding: .1rem .3rem; border-radius: .2rem;
        word-break: break-all; }}
 ol {{ padding-left: 1.2rem; }}
 .muted {{ color: #666; font-size: .9rem; }}
 .warn {{ border: 2px solid #b00; background: #fff0f0; color: #900;
        padding: 1rem 1.2rem; border-radius: .4rem; margin-bottom: 1.5rem; }}
 @media (prefers-color-scheme: dark) {{
   body {{ background: #111; color: #eee; }}
   a.btn {{ background: #eee; color: #111; }}
   code {{ background: #222; }}
   .muted {{ color: #999; }}
   .warn {{ background: #2a1010; color: #ff9a9a; border-color: #d33; }}
 }}
</style></head><body>
<h1>{label} telemetry agent</h1>
{warning}
<p>This adds <strong>{unlocks}</strong> to your instrument cluster. Those channels
are not on the network — they can only be read on this PC.</p>
<p><a class="btn" href="/{filename}">Download {filename}</a></p>
<ol>
  <li>Unzip it anywhere. No installation, no admin rights.</li>
  <li>Double-click <code>run.bat</code> &mdash; once.</li>
</ol>
<p>It already knows your cluster's address. After that one run the agent keeps
running in the background and starts again with Windows by itself &mdash;
nothing to remember before you play. It waits for a session, so start the game
whenever you like. <code>uninstall.bat</code> in the same folder removes it.</p>
<p class="muted">Version {version}<br>SHA-256 {sha256}</p>
</body></html>
"""
