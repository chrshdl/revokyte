"""Protocol v1 conformance suite.

Pins three things together:

1. The golden samples in ``tools/protocol/samples`` match the schema
   (valid ones validate, invalid ones fail — each for its intended reason).
2. The stdlib validator (``tools/protocol/validate.py``) agrees with the
   reference ``jsonschema`` package on every sample frame. The validator
   interprets only the keyword subset the v1 schema uses; this cross-check
   is what licenses that shortcut.
3. The golden session is exactly what ``synthetic_feed.py`` generates —
   drift in the generator shows up as a byte diff here, not as a silently
   different golden file.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "docs" / "telemetry-frame.v1.schema.json"
KIT = REPO / "tools" / "protocol"
SAMPLES = KIT / "samples"

VALID_FILES = [
    SAMPLES / "minimal.ndjson",
    SAMPLES / "full.ndjson",
    SAMPLES / "optional-absent.ndjson",
    SAMPLES / "golden-session.ndjson",
]
INVALID_FILES = sorted((SAMPLES / "invalid").glob("*.ndjson"))


def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, KIT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate_tool = _load_tool("validate")
synthetic_feed = _load_tool("synthetic_feed")

SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
REFERENCE = Draft202012Validator(SCHEMA)


def _frames(path: Path):
    return [(n, frame) for n, frame, _dt in validate_tool.iter_frames(path)]


def test_schema_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("path", VALID_FILES, ids=lambda p: p.name)
def test_valid_samples_validate(path):
    assert validate_tool.check_file(path, SCHEMA) == []


@pytest.mark.parametrize("path", INVALID_FILES, ids=lambda p: p.name)
def test_invalid_samples_fail_every_line(path):
    """Each invalid sample line must trip at least one rule — a line that
    passes silently is a sample that no longer demonstrates anything."""
    per_line = {n: [] for n, _ in _frames(path)}
    for err in validate_tool.check_file(path, SCHEMA):
        line = int(err.split(":", 1)[0].removeprefix("line "))
        per_line[line].append(err)
    clean = [n for n, errs in per_line.items() if not errs]
    assert not clean, f"lines {clean} of {path.name} validate but should not"


@pytest.mark.parametrize(
    "path", VALID_FILES + INVALID_FILES, ids=lambda p: p.name
)
def test_stdlib_validator_agrees_with_jsonschema(path):
    """Same verdict, frame by frame, as the reference implementation."""
    for n, frame in _frames(path):
        ours = not validate_tool.validate_frame(frame, SCHEMA)
        reference = REFERENCE.is_valid(frame)
        assert ours == reference, (
            f"{path.name} line {n}: stdlib validator says "
            f"{'valid' if ours else 'invalid'}, jsonschema says "
            f"{'valid' if reference else 'invalid'}"
        )


def test_synthetic_session_is_conformant_over_time():
    """The scripted session stays schema-valid well past the golden window
    (gear changes, lap rollover at 90 s, fuel floor)."""
    for tenth in range(0, 2000, 7):  # 0 .. 200 s in 0.7 s steps
        frame = synthetic_feed.frame_at(tenth / 10.0)
        errors = validate_tool.validate_frame(frame, SCHEMA)
        assert not errors, f"t={tenth / 10.0}: {errors}"
        assert REFERENCE.is_valid(frame)


def test_golden_session_matches_generator(tmp_path):
    """Regeneration is byte-identical (documented in tools/protocol/README)."""
    out = tmp_path / "regen.ndjson"
    rc = synthetic_feed.main(
        ["--record", str(out), "--rate", "10", "--duration", "30"]
    )
    assert rc == 0
    assert out.read_bytes() == (SAMPLES / "golden-session.ndjson").read_bytes()


def test_golden_session_replays_in_the_app():
    """The golden session doubles as an app-level replay fixture."""
    from instrument_cluster.telemetry.udp_jsonl import ReplayReader

    reader = ReplayReader(SAMPLES / "golden-session.ndjson", loop=False)
    reader.start()
    frame = reader.latest()
    assert frame is not None
    assert frame.track_name == "Synthetic Ring"


def test_cli_exit_codes(tmp_path):
    """The CLI is the CI surface for the sibling repos; pin its contract."""
    cmd = [sys.executable, str(KIT / "validate.py")]
    ok = subprocess.run(
        [*cmd, str(SAMPLES / "minimal.ndjson")], capture_output=True
    )
    assert ok.returncode == 0
    bad = subprocess.run(
        [*cmd, str(SAMPLES / "invalid" / "null-gear.ndjson")],
        capture_output=True,
    )
    assert bad.returncode == 1
    missing = subprocess.run(
        [*cmd, str(tmp_path / "nope.ndjson")], capture_output=True
    )
    assert missing.returncode == 2
