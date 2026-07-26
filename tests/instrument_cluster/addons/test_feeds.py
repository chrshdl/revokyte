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
