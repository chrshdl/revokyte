"""The LAN hand-off of a feed's PC agent.

The point of serving the bundle from the appliance rather than linking the user
to a release page is that the download can be personalised on the way out: the
copy the user gets already knows this cluster's address. These tests cover that
rewrite, because getting it wrong produces a bundle that looks fine and silently
sends telemetry nowhere.
"""

import io
import json
import zipfile

import pytest

from instrument_cluster.addons.agent_server import (
    CONFIG_NAME,
    _PAGE,
    _UNVERIFIED_BANNER,
    AgentUnavailable,
    _replace_output,
    _write_config,
    prepare_bundle,
)
from instrument_cluster.addons.feeds import feed_by_id

CONFIG_TEMPLATE = """\
{
  "output": "udp://127.0.0.1:5600",
  "title": "acc",
  "interval_ms": 16,
  "heartbeat_max_s": 3.0
}
"""


def _bundle(tmp_path, config: str | None = CONFIG_TEMPLATE):
    path = tmp_path / "acc-agent-win-0.1.2.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("acc-agent-win-0.1.2/run.bat", "@echo off\n")
        archive.writestr("acc-agent-win-0.1.2/acc/__init__.py", "")
        archive.writestr("acc-agent-win-0.1.2/runtime/python.exe", b"\x00binary")
        if config is not None:
            archive.writestr(f"acc-agent-win-0.1.2/{CONFIG_NAME}", config)
    return path


def _read_config(path) -> dict:
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist() if n.endswith(CONFIG_NAME))
        return json.loads(archive.read(name))


def test_config_is_pointed_at_this_cluster(tmp_path):
    path = _bundle(tmp_path)
    _write_config(path, "192.168.1.42")
    assert _read_config(path)["output"] == "udp://192.168.1.42:5600"


def test_rewrite_leaves_the_rest_of_the_bundle_alone(tmp_path):
    path = _bundle(tmp_path)
    before = zipfile.ZipFile(path).namelist()
    _write_config(path, "10.0.0.5")

    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert archive.namelist() == before
        # The interpreter must survive the round-trip byte for byte.
        assert archive.read("acc-agent-win-0.1.2/runtime/python.exe") == b"\x00binary"

    config = _read_config(path)
    assert config["title"] == "acc"
    assert config["interval_ms"] == 16
    assert config["heartbeat_max_s"] == 3.0


def test_rewrite_keeps_the_file_valid_json(tmp_path):
    # The agent parses this with json.load; a broken comma would leave it
    # falling back to defaults and sending frames to localhost on the PC.
    path = _bundle(tmp_path)
    _write_config(path, "172.16.9.9")
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist() if n.endswith(CONFIG_NAME))
        json.loads(archive.read(name))  # raises if the rewrite broke the syntax


def test_bundle_without_a_config_is_served_unmodified(tmp_path):
    path = _bundle(tmp_path, config=None)
    before = path.read_bytes()
    _write_config(path, "192.168.1.42")
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "line",
    [
        '  "output": "udp://127.0.0.1:5600",',
        '"output":"udp://1.2.3.4:5600",',
        '\t"output": "udp://127.0.0.1:5600"',
    ],
)
def test_output_line_shapes(line):
    text = "{\n" + line + '\n  "title": "acc"\n}\n'
    result = _replace_output(text, '"output": "udp://192.168.1.42:5600"')
    assert "192.168.1.42" in result
    assert "127.0.0.1" not in result
    # A trailing comma must survive, or the file stops being valid JSON.
    if line.rstrip().endswith(","):
        assert result.splitlines()[1].rstrip().endswith(",")


def test_local_override_serves_a_locally_built_bundle(tmp_path, monkeypatch):
    # The agent half of a feed only reaches a release after merge and tag, so
    # without this a change to it is untestable through this screen.
    path = _bundle(tmp_path)
    monkeypatch.setenv("AGENT_BUNDLE_PATH", str(path))
    bundle = prepare_bundle(feed_by_id("acc"), "192.168.1.42")

    assert bundle.filename == path.name
    # Still personalised — the point is to exercise the real flow.
    assert _read_config(bundle.path)["output"] == "udp://192.168.1.42:5600"
    # ...and served from a copy, so the source zip is left alone.
    assert bundle.path != path
    assert _read_config(path)["output"] == "udp://127.0.0.1:5600"


def test_unsigned_override_is_flagged_all_the_way_to_the_page(tmp_path, monkeypatch):
    # The person who needs to know is the one about to run a .bat on their
    # gaming PC, so "unverified" has to survive to the download page.
    path = _bundle(tmp_path)
    monkeypatch.setenv("AGENT_BUNDLE_PATH", str(path))
    bundle = prepare_bundle(feed_by_id("acc"), "192.168.1.42")
    assert bundle.verified is False

    page = _PAGE.format(
        label="ACC", unlocks="RPM", filename=bundle.filename,
        sha256=bundle.sha256, version="v0.1.2",
        warning="" if bundle.verified else _UNVERIFIED_BANNER,
    )
    assert "Unverified build" in page
    assert "not signed by the project's release key" in page


def test_signed_override_is_verified_like_a_release_asset(tmp_path, monkeypatch):
    # The override is a way to serve a local file, not a way to skip the
    # signature check: a .sig beside it is checked exactly as CI's would be.
    path = _bundle(tmp_path)
    path.with_name(path.name + ".sig").write_bytes(b"a-good-signature")
    # Stubbed: what is under test is the branch, not Ed25519 itself — the
    # refusal case below exercises the real verifier.
    monkeypatch.setattr(
        "instrument_cluster.addons.agent_server.verify_signature",
        lambda data, sig, pub: True,
    )
    monkeypatch.setenv("AGENT_BUNDLE_PATH", str(path))

    bundle = prepare_bundle(feed_by_id("acc"), "192.168.1.42")
    assert bundle.verified is True
    page = _PAGE.format(
        label="ACC", unlocks="RPM", filename=bundle.filename,
        sha256=bundle.sha256, version="v0.1.2",
        warning="" if bundle.verified else _UNVERIFIED_BANNER,
    )
    assert "Unverified build" not in page


def test_override_with_a_bad_signature_is_refused(tmp_path, monkeypatch):
    # Present-and-wrong is never a development convenience.
    path = _bundle(tmp_path)
    path.with_name(path.name + ".sig").write_bytes(b"\x00" * 64)
    monkeypatch.setenv("AGENT_BUNDLE_PATH", str(path))
    with pytest.raises(AgentUnavailable, match="does not verify"):
        prepare_bundle(feed_by_id("acc"), "192.168.1.42")


def test_local_override_with_a_bad_path_says_so(monkeypatch):
    monkeypatch.setenv("AGENT_BUNDLE_PATH", "/nope/not-here.zip")
    with pytest.raises(AgentUnavailable, match="not a file"):
        prepare_bundle(feed_by_id("acc"), "192.168.1.42")


def test_acc_declares_an_agent_matching_the_feeds_release():
    acc = feed_by_id("acc")
    assert acc.agent is not None
    # The agent ships in the same pinned release as the proxy tarball, so the
    # two halves of the feed can never be a version apart.
    assert acc.agent.asset_prefix.startswith("acc-agent")
    assert acc.agent.asset_suffix == ".zip"
    assert acc.agent.unlocks


def test_granturismo_declares_no_agent():
    # GT7 sends everything over the network; nothing to install on a console.
    assert feed_by_id("granturismo").agent is None
