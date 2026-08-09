#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
"""Revokyte Telemetry Protocol v1 conformance validator.

Validates telemetry frames against ``docs/telemetry-frame.v1.schema.json``
using nothing but the Python standard library, so it runs anywhere a feed
runs — including on the appliance, where feeds may vendor nothing.

It is not a general JSON Schema implementation: it interprets exactly the
keyword subset the v1 schema uses (``type``, ``const``, ``minimum``,
``maximum``, ``required``, ``properties``, ``items``, ``oneOf``, ``$ref``
into ``$defs``). ``tests/protocol/test_conformance.py`` in the revokyte
repository cross-checks its verdicts against the reference ``jsonschema``
package on every golden sample, which is what keeps this subset honest.

Usage:
    validate.py [--schema PATH] FILE [FILE ...]

Each FILE is NDJSON: one JSON object per line. Two line shapes are accepted
and may not be mixed within a file:

  wire frames        {"car_speed": 33.4, ...}
  recording envelope {"dt": 1.234, "frame": {...}}   (dt must not decrease)

Exit status: 0 all frames valid, 1 any invalid frame, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_DEFAULT_SCHEMA = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "telemetry-frame.v1.schema.json"
)


# ---------------------------------------------------------------------------
# Schema interpreter (the subset the v1 schema uses)
# ---------------------------------------------------------------------------

def _is_type(value: object, name: str) -> bool:
    # bool is a subclass of int in Python but a distinct type in JSON.
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "integer":
        if isinstance(value, bool):
            return False
        # JSON Schema: 1.0 is a valid integer.
        return isinstance(value, int) or (
            isinstance(value, float) and value.is_integer()
        )
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise ValueError(f"schema uses unsupported type {name!r}")


def _resolve_ref(schema_root: dict, ref: str) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported $ref {ref!r} (only local refs)")
    node: object = schema_root
    for part in ref[2:].split("/"):
        node = node[part]  # type: ignore[index]
    return node  # type: ignore[return-value]


def _validate(value, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    if "$ref" in schema:
        _validate(value, _resolve_ref(root, schema["$ref"]), root, path, errors)
        return

    if "oneOf" in schema:
        matches = 0
        for sub in schema["oneOf"]:
            probe: list[str] = []
            _validate(value, sub, root, path, probe)
            if not probe:
                matches += 1
        if matches != 1:
            errors.append(
                f"{path or '<root>'}: matches {matches} of the oneOf variants"
                " (exactly one required)"
            )
        return

    if "const" in schema:
        expected = schema["const"]
        if type(value) is not type(expected) and not (
            isinstance(expected, (int, float))
            and isinstance(value, (int, float))
            and not isinstance(expected, bool)
            and not isinstance(value, bool)
        ):
            errors.append(f"{path or '<root>'}: must be {expected!r}")
            return
        if value != expected:
            errors.append(f"{path or '<root>'}: must be {expected!r}")
            return

    if "type" in schema:
        names = schema["type"]
        if isinstance(names, str):
            names = [names]
        if not any(_is_type(value, n) for n in names):
            errors.append(
                f"{path or '<root>'}: {json.dumps(value)[:60]} is not of type "
                f"{' or '.join(names)}"
            )
            return  # type failed: the remaining keywords are meaningless

    is_num = isinstance(value, (int, float)) and not isinstance(value, bool)
    if is_num and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path or '<root>'}: {value} is below minimum {schema['minimum']}")
    if is_num and "maximum" in schema and value > schema["maximum"]:
        errors.append(f"{path or '<root>'}: {value} exceeds maximum {schema['maximum']}")
    if is_num and "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
        errors.append(
            f"{path or '<root>'}: {value} is not above {schema['exclusiveMinimum']}"
        )

    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path or '<root>'}: missing required key {req!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                child = f"{path}/{key}" if path else key
                _validate(value[key], sub, root, child, errors)
        # additionalProperties is `true` throughout the v1 schema (tolerant
        # reader): unknown keys are always allowed.

    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _validate(item, schema["items"], root, f"{path}[{i}]", errors)


def validate_frame(frame: object, schema: dict) -> list[str]:
    """All conformance errors for one frame ([] means the frame is valid)."""
    errors: list[str] = []
    _validate(frame, schema, schema, "", errors)
    return errors


# ---------------------------------------------------------------------------
# File handling
# ---------------------------------------------------------------------------

def iter_frames(path: Path):
    """Yield ``(line_number, frame, dt)`` per line; dt is None for wire lines."""
    with path.open(encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            if not line.strip():
                continue
            obj = json.loads(line)
            if isinstance(obj, dict) and set(obj) == {"dt", "frame"}:
                yield n, obj["frame"], obj["dt"]
            else:
                yield n, obj, None


def check_file(path: Path, schema: dict) -> list[str]:
    """All errors in one NDJSON file, prefixed with line numbers."""
    errors: list[str] = []
    last_dt = None
    try:
        for n, frame, dt in iter_frames(path):
            if dt is not None:
                if not isinstance(dt, (int, float)) or isinstance(dt, bool):
                    errors.append(f"line {n}: dt is not a number")
                elif last_dt is not None and dt < last_dt:
                    errors.append(f"line {n}: dt {dt} decreases (was {last_dt})")
                else:
                    last_dt = dt
            for e in validate_frame(frame, schema):
                errors.append(f"line {n}: {e}")
    except json.JSONDecodeError as e:
        errors.append(f"line {e.lineno}: not valid JSON: {e.msg}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate Revokyte Telemetry Protocol v1 NDJSON files"
    )
    parser.add_argument("files", nargs="+", type=Path, metavar="FILE")
    parser.add_argument(
        "--schema",
        type=Path,
        default=_DEFAULT_SCHEMA,
        help=f"schema to validate against (default: {_DEFAULT_SCHEMA})",
    )
    args = parser.parse_args(argv)

    try:
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot load schema {args.schema}: {e}", file=sys.stderr)
        return 2

    failed = False
    for path in args.files:
        if not path.exists():
            print(f"{path}: no such file", file=sys.stderr)
            return 2
        errors = check_file(path, schema)
        count = sum(1 for _ in iter_frames(path)) if not errors else "?"
        if errors:
            failed = True
            print(f"{path}: INVALID")
            for e in errors[:20]:
                print(f"  {e}")
            if len(errors) > 20:
                print(f"  ... and {len(errors) - 20} more")
        else:
            print(f"{path}: OK ({count} frames)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
