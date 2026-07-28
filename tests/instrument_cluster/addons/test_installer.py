"""Tests for the descriptor-driven installer (addons/installer.py)."""

import base64
import io
import json
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from instrument_cluster.addons import installer
from instrument_cluster.addons.feeds import feed_by_id


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _release_json():
    # A release exposing both feeds' assets; resolve must pick by prefix.
    return {
        "assets": [
            {
                "name": "granturismo-selfcontained-0.3.14.tar.gz",
                "browser_download_url": "https://example/gt7.tar.gz",
            },
            {
                "name": "acc-selfcontained-1.0.0.tar.gz",
                "browser_download_url": "https://example/acc.tar.gz",
            },
            {"name": "unrelated.txt", "browser_download_url": "https://example/x"},
        ]
    }


def test_resolve_picks_asset_by_descriptor_prefix(monkeypatch):
    payload = json.dumps(_release_json()).encode()
    monkeypatch.setattr(
        installer.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(payload),
    )

    assert (
        installer.resolve_pinned_tarball_url(feed_by_id("granturismo"))
        == "https://example/gt7.tar.gz"
    )
    assert (
        installer.resolve_pinned_tarball_url(feed_by_id("acc"))
        == "https://example/acc.tar.gz"
    )


def test_resolve_returns_none_when_no_matching_asset(monkeypatch):
    payload = json.dumps({"assets": []}).encode()
    monkeypatch.setattr(
        installer.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(payload),
    )
    assert installer.resolve_pinned_tarball_url(feed_by_id("acc")) is None


def test_resolve_raises_feed_unreachable_on_network_error(monkeypatch):
    """Still fails closed (nothing gets installed), but distinguishably: an
    offline device must not be told the feed has no release."""

    def _boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(installer.urllib.request, "urlopen", _boom)
    with pytest.raises(installer.FeedUnreachable, match="network down"):
        installer.resolve_pinned_tarball_url(feed_by_id("acc"))


def test_verify_signature_uses_descriptor_pubkey():
    key = Ed25519PrivateKey.generate()
    pub_b64 = base64.b64encode(
        key.public_key().public_bytes_raw()
    ).decode()
    data = b"release-tarball-bytes"
    sig = key.sign(data)

    assert installer.verify_signature(data, sig, pub_b64) is True
    assert installer.verify_signature(b"tampered", sig, pub_b64) is False


def test_descriptor_can_override_signing_key():
    # A feed signed with its own key carries that pubkey on its descriptor.
    key = Ed25519PrivateKey.generate()
    pub_b64 = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    acc = replace(feed_by_id("acc"), signing_pubkey_b64=pub_b64)

    data = b"acc-bundle"
    sig = key.sign(data)
    assert installer.verify_signature(data, sig, acc.signing_pubkey_b64) is True


def test_resolve_still_returns_none_when_release_lacks_the_asset(monkeypatch):
    """A reachable API with no matching asset is NOT a network failure."""
    payload = json.dumps({"assets": [{"name": "something-else.zip"}]}).encode()
    monkeypatch.setattr(
        installer.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(payload),
    )
    assert installer.resolve_pinned_tarball_url(feed_by_id("granturismo")) is None


def _http_error(code):
    import urllib.error

    def _raise(*a, **k):
        raise urllib.error.HTTPError(
            url="https://api.github.com/x", code=code, msg="nope", hdrs=None, fp=None
        )

    return _raise


@pytest.mark.parametrize("code", [403, 429])
def test_rate_limited_is_not_reported_as_offline(monkeypatch, code):
    """GitHub answering at all proves the link works.

    Unauthenticated release lookups share a 60/hour budget per public IP, so
    a household behind CGNAT can hit this. Telling its owner "no network
    connection" sends them to rewire a working router.
    """
    monkeypatch.setattr(installer.urllib.request, "urlopen", _http_error(code))

    with pytest.raises(installer.FeedRateLimited):
        installer.resolve_pinned_tarball_url(feed_by_id("acc"))


def test_rate_limited_still_fails_closed(monkeypatch):
    """It remains a FeedUnreachable subclass, so existing handling that only
    knows the base class still refuses to install anything."""
    monkeypatch.setattr(installer.urllib.request, "urlopen", _http_error(403))

    with pytest.raises(installer.FeedUnreachable):
        installer.resolve_pinned_tarball_url(feed_by_id("acc"))


def test_other_http_errors_stay_plain_unreachable(monkeypatch):
    monkeypatch.setattr(installer.urllib.request, "urlopen", _http_error(500))

    with pytest.raises(installer.FeedUnreachable) as excinfo:
        installer.resolve_pinned_tarball_url(feed_by_id("acc"))
    assert not isinstance(excinfo.value, installer.FeedRateLimited)


# --- Pinning ---------------------------------------------------------------


def test_resolve_asks_for_the_pinned_tag_not_latest(monkeypatch):
    """The device installs the release the descriptor pins.

    A feed published after this image was built can speak a TelemetryFrame
    shape the image doesn't — the exact failure the received_time stamping
    fixed, only arriving silently on someone else's schedule.
    """
    seen = {}

    def _capture(req, *a, **k):
        seen["url"] = req.full_url
        return _FakeResponse(json.dumps(_release_json()).encode())

    monkeypatch.setattr(installer.urllib.request, "urlopen", _capture)
    descriptor = feed_by_id("granturismo")
    installer.resolve_pinned_tarball_url(descriptor)

    assert seen["url"].endswith(f"/releases/tags/{descriptor.version}")
    assert "/releases/latest" not in seen["url"]


def test_a_missing_pinned_release_is_not_reported_as_offline(monkeypatch):
    """404 means GitHub answered authoritatively: the tag isn't published.

    That's a packaging fault, so it must not send someone to the router.
    """
    monkeypatch.setattr(installer.urllib.request, "urlopen", _http_error(404))

    with pytest.raises(installer.FeedVersionMissing) as excinfo:
        installer.resolve_pinned_tarball_url(feed_by_id("acc"))

    assert not isinstance(excinfo.value, installer.FeedUnreachable)
    assert "v0.1.0" in str(excinfo.value)


# --- Recovering the configured address -------------------------------------


@pytest.mark.parametrize(
    "body, expected",
    [
        ("GT_PS_IP=192.168.1.50\nGT_JSONL_OUTPUT=udp://127.0.0.1:5600\n", "192.168.1.50"),
        ("ACC_PC_IP=10.0.0.7\nACC_UDP_PORT=9000\n", "10.0.0.7"),
        ("GT_JSONL_OUTPUT=udp://127.0.0.1:5600\n", ""),
        ("", ""),
    ],
)
def test_installed_feed_ip_reads_whatever_key_the_feed_uses(
    tmp_path, monkeypatch, body, expected
):
    """Matched on the shared _IP suffix, so it works per-feed without the
    installer knowing any particular one."""
    env = tmp_path / "proxy-env"
    env.write_text(body)
    monkeypatch.setattr(installer, "ENV_FILE", env)

    assert installer.installed_feed_ip() == expected


def test_installed_feed_ip_is_empty_without_an_env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(installer, "ENV_FILE", tmp_path / "missing")
    assert installer.installed_feed_ip() == ""
