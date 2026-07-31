"""Generate the calibrated engine-parameter artifact for every car.

Fits the crank-angle engine model (core/engine_sim) to each entry in
db/cars.json — archetype classification, staged calibration, bounded
correction — and writes db/engine_params.json, which the runtime bakes
torque/fuel maps from. Run this whenever cars.json, the archetype
templates, the fitter, or the physics change, and commit the result:
the device never fits, it only bakes.

Usage (from repo root, venv active):

    python tools/engine_sim/fit_cars.py                # all cars
    python tools/engine_sim/fit_cars.py --only 37      # one car, verbose
    python tools/engine_sim/fit_cars.py --report       # summary of failures
    python tools/engine_sim/fit_cars.py --jobs 8       # parallel fit
"""

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))

from instrument_cluster.core.engine_sim.calibrate import fit_car  # noqa: E402

CARS_PATH = REPO / "src" / "instrument_cluster" / "db" / "cars.json"
OVERRIDES_PATH = Path(__file__).resolve().parent / "overrides.json"
ARTIFACT_PATH = REPO / "src" / "instrument_cluster" / "db" / "engine_params.json"

# The CarLibrary fallback profile (core/vehicle/car_profiler.py): unknown
# GT7 car ids get a map fitted to the same generic engine the heuristic
# would use.
DEFAULT_SPECS = {
    "name": None,
    "max_power_kw": 300,
    "max_power_rpm": 7000,
    "max_torque_nm": 450,
    "max_torque_rpm": 5000,
    "redline_rpm": 8500,
}


def _round_floats(obj, ndigits=6):
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, ndigits) for v in obj]
    return obj


def _fit_one(item):
    car_id, specs, overrides = item
    outcome = fit_car(car_id, specs, overrides)
    entry = {
        "name": specs.get("name"),
        "archetype": outcome.archetype,
        "fit": outcome.fit,
        "params": outcome.params.to_dict() if outcome.params else None,
        "fit_error": outcome.fit_error,
    }
    return str(car_id), entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="fit a single car id and print the result")
    parser.add_argument("--report", action="store_true",
                        help="print a fit summary instead of only writing")
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()

    with open(CARS_PATH, encoding="utf-8") as f:
        cars = json.load(f)
    with open(OVERRIDES_PATH, encoding="utf-8") as f:
        overrides = {k: v for k, v in json.load(f).items() if not k.startswith("_")}

    if args.only:
        specs = cars[args.only] if args.only != "default" else DEFAULT_SPECS
        car_id, entry = _fit_one((args.only, specs, overrides))
        print(json.dumps(_round_floats(entry), indent=2))
        return 0

    work = [(cid, specs, overrides) for cid, specs in cars.items()]
    work.append(("default", DEFAULT_SPECS, overrides))

    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            results = dict(pool.map(_fit_one, work, chunksize=4))
    else:
        results = dict(_fit_one(item) for item in work)

    # Deterministic artifact: numeric ids sorted, floats rounded.
    ordered = {}
    for cid in sorted(results, key=lambda c: (c != "default", int(c) if c.isdigit() else 0)):
        ordered[cid] = _round_floats(results[cid])

    with open(ARTIFACT_PATH, "w", encoding="utf-8") as f:
        json.dump(ordered, f, indent=1, sort_keys=False)
        f.write("\n")

    counts = {}
    for entry in results.values():
        counts[entry["fit"]] = counts.get(entry["fit"], 0) + 1
    print(f"wrote {ARTIFACT_PATH} ({len(results)} entries): {counts}")

    if args.report:
        print("\nfailed fits:")
        for cid, entry in ordered.items():
            if entry["fit"] == "failed":
                print(f"  {cid:>6} {str(entry['name'])[:40]:40} "
                      f"{entry['archetype']:12} {entry['fit_error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
