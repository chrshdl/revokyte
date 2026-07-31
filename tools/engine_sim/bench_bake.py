"""Measure the on-device cost of one background map bake.

Run this on the Pi (and on dev for reference) before trusting the
bake-at-car-change design: the number that matters is wall time of a
full-resolution bake for a typical car, with and without the pace hook's
frame-loop-friendly sleeps.

Usage (from repo root, venv active):

    python tools/engine_sim/bench_bake.py [--car-id 37] [--runs 3]
"""

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from instrument_cluster.core.engine_sim.engine import EngineSimulator  # noqa: E402
from instrument_cluster.core.engine_sim.params import EngineParams  # noqa: E402
from instrument_cluster.core.engine_sim.service import _THROTTLE_AXIS, _RPM_STEP  # noqa: E402

ARTIFACT_PATH = REPO / "src" / "instrument_cluster" / "db" / "engine_params.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--car-id", default="37")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    entry = json.load(open(ARTIFACT_PATH, encoding="utf-8"))[args.car_id]
    if entry["fit"] != "ok":
        print(f"car {args.car_id} has no ok fit")
        return 1
    params = EngineParams.from_dict(entry["params"])
    rpm_axis = np.arange(params.idle_rpm, 1.05 * params.rated_rpm + _RPM_STEP, _RPM_STEP)
    print(f"{entry['name']}: grid {len(rpm_axis)} rpm x {len(_THROTTLE_AXIS)} throttle")

    for label, hook in (("no pace hook ", None),
                        ("2ms pace hook", lambda: time.sleep(0.002))):
        times = []
        for _ in range(args.runs):
            sim = EngineSimulator(params)
            t0 = time.perf_counter()
            sim.simulate_grid(rpm_axis, _THROTTLE_AXIS, pace_hook=hook)
            times.append(time.perf_counter() - t0)
        print(f"  {label}: min {min(times)*1e3:6.0f} ms  "
              f"mean {sum(times)/len(times)*1e3:6.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
