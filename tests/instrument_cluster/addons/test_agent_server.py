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


def test_the_pinned_release_is_the_only_source(monkeypatch, tmp_path):
    """Regression guard: no environment variable may divert this to a local file.

    An earlier revision had an AGENT_BUNDLE_PATH escape hatch for testing an
    unreleased agent. It was removed because this server hands a Windows
    executable to another machine under the appliance's own name, and "set this
    variable, then open that page" is a plausible thing to talk someone into.
    Test an unreleased agent with a prerelease tag instead.
    """
    local = _bundle(tmp_path)
    for name in ("AGENT_BUNDLE_PATH", "AGENT_BUNDLE", "BUNDLE_PATH"):
        monkeypatch.setenv(name, str(local))
    monkeypatch.setattr(
        "instrument_cluster.addons.agent_server.resolve_pinned_agent_url",
        lambda descriptor: None,
    )
    # Still fails closed on a release with no asset, rather than reaching for
    # the local file the environment is pointing at.
    with pytest.raises(AgentUnavailable, match="has no acc-agent-win-"):
        prepare_bundle(feed_by_id("acc"), "192.168.1.42")


def test_an_unsigned_release_is_flagged_on_the_download_page():
    # The signature check is not optional, but a release predating the signing
    # key still has to be usable — so it is served and labelled, and the label
    # reaches the person about to run it.
    page = _PAGE.format(
        label="ACC", unlocks="RPM", filename="acc-agent-win-0.1.2.zip",
        sha256="deadbeef", version="v0.1.2", warning=_UNVERIFIED_BANNER,
    )
    assert "Unverified build" in page
    assert "not signed by the project's release key" in page
    # ...and stays out of the way when there is nothing to warn about.
    clean = _PAGE.format(
        label="ACC", unlocks="RPM", filename="acc-agent-win-0.1.2.zip",
        sha256="deadbeef", version="v0.1.2", warning="",
    )
    assert "Unverified" not in clean


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
