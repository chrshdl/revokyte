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
        installer.resolve_latest_tarball_url(feed_by_id("granturismo"))
        == "https://example/gt7.tar.gz"
    )
    assert (
        installer.resolve_latest_tarball_url(feed_by_id("acc"))
        == "https://example/acc.tar.gz"
    )


def test_resolve_returns_none_when_no_matching_asset(monkeypatch):
    payload = json.dumps({"assets": []}).encode()
    monkeypatch.setattr(
        installer.urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResponse(payload),
    )
    assert installer.resolve_latest_tarball_url(feed_by_id("acc")) is None


def test_resolve_raises_feed_unreachable_on_network_error(monkeypatch):
    """Still fails closed (nothing gets installed), but distinguishably: an
    offline device must not be told the feed has no release."""

    def _boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(installer.urllib.request, "urlopen", _boom)
    with pytest.raises(installer.FeedUnreachable, match="network down"):
        installer.resolve_latest_tarball_url(feed_by_id("acc"))


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
    assert installer.resolve_latest_tarball_url(feed_by_id("granturismo")) is None
