"""Regenerate ``db/car_classes.json`` from the gt-telemetry vehicle inventory.

The shift-point curve needs to know how fast an engine loses power past its
peak, and the four peaks a sender can put on the wire do not say. What does
say — approximately, but far better than one boolean — is *what kind of car
it is*: a turbocharged road car falls off a cliff, a BOP'd race engine holds
power to the limiter, a high-revving NA sits between them.

[zetetos/gt-telemetry](https://github.com/zetetos/gt-telemetry) (MIT) keeps
exactly that classification, one JSON per GT7 ``carId``, in
``pkg/vehicles/inventory``. This script downloads the repository once,
extracts the four fields the curve model uses, and writes them keyed by car
id. Unlike ``cars.json`` — which has no recorded provenance and no
generator — the table this writes can always be rebuilt from source.

    python tools/fetch_car_classes.py              # rewrite the table
    python tools/fetch_car_classes.py --check      # report only, no write

``--check`` is also the drift check: it exits non-zero if the file on disk
differs from what upstream would produce now, so a stale table is visible
without diffing 500 lines by hand.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
import urllib.request
from collections import Counter
from pathlib import Path

# A repository tarball is one request; the inventory is ~580 files, and
# fetching them individually through the API burns a rate limit for no gain.
_TARBALL = "https://codeload.github.com/zetetos/gt-telemetry/tar.gz/refs/heads/main"
_INVENTORY_DIR = "pkg/vehicles/inventory/"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CARS_JSON = _REPO_ROOT / "src/instrument_cluster/db/cars.json"
_OUT_JSON = _REPO_ROOT / "src/instrument_cluster/db/car_classes.json"

# Upstream's field name -> ours. Only what the curve model reads: aspiration
# and car type pick the falloff, category and engine layout are carried for
# the finer splits (rotaries, Gr.B) a measurement may later ask for.
_FIELDS = {
    "aspiration": "aspiration",
    "carType": "car_type",
    "category": "category",
    "engineLayout": "engine_layout",
}


def fetch_inventory(url: str = _TARBALL) -> dict[str, dict[str, str]]:
    """Download the upstream repo and return ``{car_id: {field: value}}``."""
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
        blob = response.read()

    out: dict[str, dict[str, str]] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile() or _INVENTORY_DIR not in member.name:
                continue
            if not member.name.endswith(".json"):
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            vehicle = json.loads(handle.read())
            car_id = vehicle.get("carId")
            if car_id is None:
                continue
            out[str(car_id)] = {
                ours: str(vehicle.get(theirs) or "").strip()
                for theirs, ours in _FIELDS.items()
            }
    return out


def render(classes: dict[str, dict[str, str]]) -> str:
    """Serialise numerically sorted, one car per line — a readable diff."""
    lines = ["{"]
    for i, car_id in enumerate(sorted(classes, key=int)):
        entry = json.dumps(classes[car_id], separators=(", ", ": "))
        comma = "," if i < len(classes) - 1 else ""
        lines.append(f'  "{car_id}": {entry}{comma}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def report(classes: dict[str, dict[str, str]]) -> None:
    known = set(json.loads(_CARS_JSON.read_text()))
    inventory = set(classes)
    missing = sorted(known - inventory, key=int)

    print(f"inventory: {len(inventory)} cars   cars.json: {len(known)} cars")
    print(f"covered:   {len(known & inventory)}/{len(known)}")
    if missing:
        print(f"MISSING from the inventory: {', '.join(missing)}")

    for field in ("aspiration", "car_type", "category"):
        counts = Counter(v[field] or "(empty)" for v in classes.values())
        tally = "  ".join(
            f"{name}={n}" for name, n in sorted(counts.items(), key=lambda kv: -kv[1])
        )
        print(f"{field:>13}: {tally}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report coverage and exit non-zero if the table on disk is stale",
    )
    parser.add_argument("--out", type=Path, default=_OUT_JSON)
    args = parser.parse_args()

    classes = fetch_inventory()
    if not classes:
        print("no vehicles found upstream — aborting", file=sys.stderr)
        return 2

    report(classes)
    payload = render(classes)

    if args.check:
        current = args.out.read_text() if args.out.exists() else ""
        if current == payload:
            print(f"\n{args.out.name} is up to date")
            return 0
        print(f"\n{args.out.name} is STALE — rerun without --check", file=sys.stderr)
        return 1

    args.out.write_text(payload)
    print(f"\nwrote {args.out} ({len(classes)} cars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
