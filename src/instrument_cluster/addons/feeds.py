"""Registry of installable telemetry feeds.

This is the *only* module in the app that is aware specific games exist, and it
holds them as **data**, not logic: each feed is a :class:`FeedDescriptor`. The
installer, the settings UI, and the IP-entry flow are all generic over a
descriptor — none of them branch on which game it is. Adding a future game is one
entry in ``FEEDS`` here plus shipping its feed program (a separate repo that
emits ``TelemetryFrame`` NDJSON to ``udp://127.0.0.1:5600``, like granturismo).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..telemetry.reader_protocol import TelemetryReaderProtocol

# Where every feed re-emits its NDJSON, and where the app's UdpJsonlReader
# listens. Shared by all feeds — the app is always "read localhost NDJSON".
JSONL_OUTPUT = "udp://127.0.0.1:5600"

# Base install directory (persisted via a symlink to /data on the appliance).
# Each feed installs into its own subdirectory below this, and the installer
# repoints ``<INSTALL_BASE>/active`` at the selected feed so the (static)
# systemd proxy service always runs ``<INSTALL_BASE>/active/proxy-wrapper.py``.
INSTALL_BASE = "/opt/telemetry"
ACTIVE_LINK = f"{INSTALL_BASE}/active"

# Public keys that verify detached Ed25519 release signatures. Each feed is
# signed with its own CI key and declares the matching public key on its
# descriptor.
GRANTURISMO_SIGNING_PUBKEY_B64 = "LxAQOYejrNcIEESiT7UiZklyDa+iyPgqvJK7IzBF97I="
ACC_SIGNING_PUBKEY_B64 = "Of2lY9Z9YbtebmGwK5OFcizQTK2gUQjw/+tjTxKdnJo="


@dataclass(frozen=True)
class PcAgent:
    """A feed whose richest channels can only be read *on the game PC*.

    Some games publish only part of their telemetry over the network. ACC's
    Broadcasting API, for instance, carries timing and placement but no engine
    RPM, pedals, tyre temperatures or fuel — those live in the game's shared
    memory, which is process-local, so no amount of network plumbing reaches
    them. A feed that declares one of these ships a small program the user runs
    on the gaming PC, and the appliance hands it over on the LAN rather than
    sending the user off to find a download.

    Pure data, like the rest of this module: the pairing screen and the little
    web server are generic over these fields and never branch on which game.
    """

    asset_prefix: str  # release asset name prefix (…-<version>.zip)
    port: int  # LAN port the appliance serves the download on
    # One line naming what the agent adds, shown on the pairing screen.
    unlocks: str
    asset_suffix: str = ".zip"


@dataclass(frozen=True)
class FeedDescriptor:
    """Everything the install flow needs to fetch, verify, configure and label
    one telemetry feed. Pure data — no behavior beyond building its env file."""

    id: str  # opaque persisted key, e.g. "granturismo", "acc"
    label: str  # human label shown in the settings dropdown
    github_repo: str  # "owner/repo" whose releases hold the tarball
    # Release tag this image installs. Pinned, never "latest": the feed and
    # the cluster share the TelemetryFrame schema, so which feed build a
    # device gets has to be a decision made when the image is built and
    # tested — not whatever happened to be published the day someone ran
    # Setup. Must match the pin in pyproject.toml's "pc" extra, which is the
    # version desktop builds read in-process (see test_feeds.py).
    version: str
    asset_prefix: str  # release asset name prefix (…-<version>.tar.gz)
    ip_prompt_title: str  # title shown on the IP-entry screen
    env_builder: Callable[[str], str]  # ip -> env-file body for the feed's proxy
    signing_pubkey_b64: str  # base64 raw Ed25519 key; every feed must declare one
    install_name: str = ""  # install subdir name; defaults to id when empty
    # Desktop builds run a feed in-process instead of installing its proxy:
    # ip -> TelemetryReaderProtocol. None = the feed only exists as an
    # installable proxy program (and is not offered on desktop).
    direct_reader: Callable[[str], TelemetryReaderProtocol] | None = None
    # Set when the game keeps some channels off the network entirely and a
    # program on the game PC is the only way to read them. None = everything
    # this feed can offer arrives over the network.
    agent: PcAgent | None = None

    @property
    def install_dir(self) -> str:
        """This feed's own subdirectory under the shared install base."""
        return f"{INSTALL_BASE}/{self.install_name or self.id}"

    def env_content(self, ip: str) -> str:
        return self.env_builder(ip)


def _granturismo_env(ip: str) -> str:
    return f"GT_PS_IP={ip}\nGT_JSONL_OUTPUT={JSONL_OUTPUT}\n"


def _granturismo_direct_reader(ip: str) -> TelemetryReaderProtocol:
    # Deferred import: granturismo is an optional dependency (the "pc"
    # extra) that the appliance image doesn't ship.
    from ..telemetry.gt7_direct import Gt7DirectReader

    return Gt7DirectReader(ip)


def _acc_env(ip: str) -> str:
    return f"ACC_PC_IP={ip}\nACC_UDP_PORT=9000\nACC_JSONL_OUTPUT={JSONL_OUTPUT}\n"


def _acc_direct_reader(ip: str) -> TelemetryReaderProtocol:
    # Deferred import: acc-telemetry is an optional dependency (the "pc"
    # extra) that the appliance image doesn't ship.
    from ..telemetry.acc_direct import AccDirectReader

    return AccDirectReader(ip)


FEEDS: list[FeedDescriptor] = [
    FeedDescriptor(
        id="granturismo",
        label="Gran Turismo 7",
        github_repo="chrshdl/granturismo",
        version="v0.3.17",
        asset_prefix="granturismo-selfcontained-",
        ip_prompt_title="Enter Playstation IP",
        env_builder=_granturismo_env,
        # Signed with the granturismo repo's Ed25519 release key (GT_SIGNING_KEY secret)
        signing_pubkey_b64=GRANTURISMO_SIGNING_PUBKEY_B64,
        direct_reader=_granturismo_direct_reader,
    ),
    FeedDescriptor(
        id="acc",
        label="Assetto Corsa Competizione",
        github_repo="chrshdl/assettocorsa",
        version="v0.1.3rc1",
        asset_prefix="acc-selfcontained-",
        ip_prompt_title="Enter Computer IP",
        env_builder=_acc_env,
        install_name="assettocorsa",
        # Signed with the assettocorsa repo's own Ed25519 release key (ACC_SIGNING_KEY secret)
        signing_pubkey_b64=ACC_SIGNING_PUBKEY_B64,
        direct_reader=_acc_direct_reader,
        agent=PcAgent(
            asset_prefix="acc-agent-win-",
            port=8321,
            unlocks="RPM, tyre temperatures, pedals and fuel",
        ),
    ),
]


def feed_by_id(feed_id: str) -> FeedDescriptor | None:
    return next((f for f in FEEDS if f.id == feed_id), None)


def feed_needs_reinstall(feed_id: str, installed_version: str) -> FeedDescriptor | None:
    """The installed feed whose build no longer matches this image's pin.

    The descriptor's ``version`` only governs what a *fresh* install fetches.
    The install itself lives under ``/data`` and survives OS updates, so a
    device can go on running a feed the current image was never tested
    against — and it would degrade exactly as silently as an unstamped
    ``received_time`` did. This is the check that notices.

    An empty ``installed_version`` counts as needing a reinstall: it means the
    feed was installed before the version was recorded, so its build is
    genuinely unknown, which is the state worth converging away from. The cost
    of being wrong is one redundant download of the very version already
    wanted.

    Returns the descriptor to re-install, or None when nothing is stale.
    """
    descriptor = feed_by_id(feed_id)
    if descriptor is None:
        return None
    return descriptor if installed_version != descriptor.version else None


@dataclass(frozen=True)
class TelemetryChoice:
    """One entry in the settings telemetry dropdown: either Demo, or a feed.

    ``value`` is what the Dropdown widget renders as the option label (it reads
    ``.value`` off each option). ``feed_id`` is None for the Demo choice.
    """

    value: str  # label rendered by the dropdown
    demo: bool
    feed_id: str | None = None


def telemetry_choices(direct_only: bool = False) -> list[TelemetryChoice]:
    """Demo plus one entry per registered feed — the dropdown option list.

    ``direct_only`` keeps only feeds with an in-process reader: desktop
    builds have no proxy installer, so proxy-only feeds are not offered.
    """
    feeds = [f for f in FEEDS if f.direct_reader is not None] if direct_only else FEEDS
    return [TelemetryChoice("Demo", demo=True)] + [
        TelemetryChoice(f.label, demo=False, feed_id=f.id) for f in feeds
    ]


def current_choice(
    choices: list[TelemetryChoice], telemetry_mode: str, telemetry_feed: str
) -> TelemetryChoice:
    """Which choice reflects the persisted config: Demo when the mode is demo,
    otherwise the installed feed (falling back to the first feed)."""
    if telemetry_mode == "demo":
        return choices[0]
    for c in choices:
        if not c.demo and c.feed_id == telemetry_feed:
            return c
    # Mode is a live feed but the id is unknown/empty — show the first feed.
    return next((c for c in choices if not c.demo), choices[0])
