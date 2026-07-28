"""Tests for the telemetry feed registry (addons/feeds.py)."""

from instrument_cluster.addons.feeds import (
    FEEDS,
    JSONL_OUTPUT,
    FeedDescriptor,
    current_choice,
    feed_by_id,
    telemetry_choices,
)


def test_registry_has_gt7_and_acc():
    ids = {f.id for f in FEEDS}
    assert {"granturismo", "acc"} <= ids


def test_feed_by_id_roundtrip():
    assert feed_by_id("acc").label == "Assetto Corsa Competizione"
    assert feed_by_id("granturismo").github_repo == "chrshdl/granturismo"
    assert feed_by_id("does-not-exist") is None


def test_each_feed_installs_into_its_own_subdir():
    assert feed_by_id("granturismo").install_dir == "/opt/telemetry/granturismo"
    assert feed_by_id("acc").install_dir == "/opt/telemetry/assettocorsa"


def test_env_content_is_feed_specific():
    gt7 = feed_by_id("granturismo").env_content("192.168.1.10")
    assert "GT_PS_IP=192.168.1.10" in gt7
    assert f"GT_JSONL_OUTPUT={JSONL_OUTPUT}" in gt7

    acc = feed_by_id("acc").env_content("192.168.1.20")
    assert "ACC_PC_IP=192.168.1.20" in acc
    assert "ACC_UDP_PORT=9000" in acc
    assert f"ACC_JSONL_OUTPUT={JSONL_OUTPUT}" in acc


def test_telemetry_choices_lead_with_demo_then_feeds():
    choices = telemetry_choices()
    assert choices[0].demo is True
    assert choices[0].value == "Demo"
    feed_ids = [c.feed_id for c in choices if not c.demo]
    assert feed_ids == [f.id for f in FEEDS]


def test_current_choice_demo_mode():
    choices = telemetry_choices()
    assert current_choice(choices, "demo", "") is choices[0]


def test_current_choice_matches_installed_feed():
    choices = telemetry_choices()
    chosen = current_choice(choices, "udp", "acc")
    assert chosen.feed_id == "acc"


def test_current_choice_udp_unknown_feed_falls_back_to_first_feed():
    choices = telemetry_choices()
    chosen = current_choice(choices, "udp", "")
    assert not chosen.demo
    assert chosen.feed_id == FEEDS[0].id


# --- Direct (in-process) readers ---


def test_both_feeds_support_direct_reading():
    assert feed_by_id("granturismo").direct_reader is not None
    assert feed_by_id("acc").direct_reader is not None


def test_direct_choices_offer_both_feeds():
    choices = telemetry_choices(direct_only=True)
    assert choices[0].demo is True
    feed_ids = [c.feed_id for c in choices if not c.demo]
    assert "granturismo" in feed_ids
    assert "acc" in feed_ids


def test_direct_only_choices_hide_proxy_only_feeds(monkeypatch):
    from instrument_cluster.addons import feeds as feeds_module

    proxy_only = FeedDescriptor(
        id="proxyonly",
        label="Proxy Only",
        github_repo="chrshdl/proxyonly",
        version="v1.0.0",
        asset_prefix="proxyonly-",
        ip_prompt_title="Enter IP",
        env_builder=lambda ip: "",
        signing_pubkey_b64="",
    )
    monkeypatch.setattr(feeds_module, "FEEDS", [*feeds_module.FEEDS, proxy_only])

    feed_ids = [
        c.feed_id for c in feeds_module.telemetry_choices(direct_only=True) if not c.demo
    ]
    assert "proxyonly" not in feed_ids
    assert feed_ids  # the direct-capable feeds are still offered


# --- Version pinning -------------------------------------------------------


def _pyproject_git_pins():
    """{package: tag} from pyproject's "pc" extra git references."""
    import re
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():  # installed without the source tree
        return None

    data = tomllib.loads(pyproject.read_text())
    pins = {}
    for spec in data["project"]["optional-dependencies"]["pc"]:
        match = re.match(r"(\S+)\s*@\s*git\+\S+/([^@]+)@(\S+)", spec)
        if match:
            pins[match.group(2)] = match.group(3)
    return pins


def test_every_feed_declares_a_pinned_version():
    from instrument_cluster.addons.feeds import FEEDS

    for feed in FEEDS:
        assert feed.version, f"{feed.id} has no pinned release"
        assert feed.version != "latest"


def test_appliance_pins_match_the_desktop_pins():
    """One feed version per image, whichever path runs it.

    The appliance installs the descriptor's pinned release; desktop builds
    read the same feed in-process from pyproject's "pc" extra. If those two
    drift, the same cluster commit speaks to two different feed builds
    depending on where it runs — which is exactly the mismatch pinning is
    supposed to rule out.
    """
    import pytest

    from instrument_cluster.addons.feeds import FEEDS

    pins = _pyproject_git_pins()
    if pins is None:
        pytest.skip("no pyproject.toml alongside the package")

    for feed in FEEDS:
        repo = feed.github_repo.split("/")[-1]
        if repo not in pins:
            continue
        assert feed.version == pins[repo], (
            f"{feed.id}: descriptor pins {feed.version}, pyproject pins "
            f"{pins[repo]}"
        )


# --- Installed-version drift ----------------------------------------------


def test_matching_installed_version_needs_no_reinstall():
    from instrument_cluster.addons.feeds import feed_by_id, feed_needs_reinstall

    pinned = feed_by_id("granturismo").version
    assert feed_needs_reinstall("granturismo", pinned) is None


def test_older_installed_version_needs_a_reinstall():
    """The install lives on /data and survives OS updates, so the pin alone
    says nothing about what is actually running."""
    from instrument_cluster.addons.feeds import feed_needs_reinstall

    stale = feed_needs_reinstall("granturismo", "v0.3.10")
    assert stale is not None
    assert stale.id == "granturismo"


def test_unknown_installed_version_needs_a_reinstall():
    """Installed before the version was recorded — genuinely unknown, which
    is the state worth converging away from. One redundant download at worst."""
    from instrument_cluster.addons.feeds import feed_needs_reinstall

    assert feed_needs_reinstall("granturismo", "") is not None


def test_no_feed_installed_needs_nothing():
    from instrument_cluster.addons.feeds import feed_needs_reinstall

    assert feed_needs_reinstall("", "") is None
    assert feed_needs_reinstall("nosuchfeed", "v1.0.0") is None
