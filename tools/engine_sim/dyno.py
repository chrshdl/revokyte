"""Offline dyno: compare the calibrated engine model against the
heuristic and the cars.json peak markers for one car.

The fitter only guarantees the two DB anchor points; this is the tool
for eyeballing everything in between — WOT torque/power shape,
part-throttle behaviour, fuel flow — before trusting a fit.

Usage (from repo root, venv active):

    python tools/engine_sim/dyno.py --car-id 37
    python tools/engine_sim/dyno.py --car-id 296 --throttle 0.5
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
from instrument_cluster.core.vehicle.ecu import EngineModel  # noqa: E402

CARS_PATH = REPO / "src" / "instrument_cluster" / "db" / "cars.json"
ARTIFACT_PATH = REPO / "src" / "instrument_cluster" / "db" / "engine_params.json"

_BAR_WIDTH = 46


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--car-id", required=True)
    parser.add_argument("--throttle", type=float, default=1.0)
    args = parser.parse_args()

    cars = json.load(open(CARS_PATH, encoding="utf-8"))
    artifact = json.load(open(ARTIFACT_PATH, encoding="utf-8"))
    specs = cars[args.car_id]
    entry = artifact.get(args.car_id)
    if entry is None or entry["fit"] != "ok":
        print(f"no usable fit for car {args.car_id}: "
              f"{entry['fit'] if entry else 'missing'} — runtime uses the heuristic")
        return 1

    params = EngineParams.from_dict(entry["params"])
    sim = EngineSimulator(params)
    heuristic = EngineModel(
        specs["max_power_kw"], specs["max_power_rpm"],
        specs["max_torque_nm"], specs["max_torque_rpm"], specs["redline_rpm"],
    )

    redline = specs["redline_rpm"]
    axis = np.arange(1000.0, 1.03 * redline, 250.0)

    t0 = time.perf_counter()
    torque, fuel = sim.simulate_grid(axis, np.asarray([args.throttle]))
    bake_ms = (time.perf_counter() - t0) * 1e3
    torque = torque[:, 0]
    fuel = fuel[:, 0]
    power_kw = torque * axis * 2 * np.pi / 60 / 1e3

    print(f"{specs['name']}  [{entry['archetype']}]  "
          f"fit_error={entry['fit_error']}  ({bake_ms:.0f} ms)")
    print(f"DB: {specs['max_torque_nm']} Nm @ {specs['max_torque_rpm']}, "
          f"{specs['max_power_kw']} kW @ {specs['max_power_rpm']}, "
          f"redline {redline}")
    print(f"\n  rpm |  model Nm | heur Nm |  kW    | fuel g/s | throttle {args.throttle:.0%}")
    scale = _BAR_WIDTH / max(float(torque.max()), 1.0)
    for i, rpm in enumerate(axis):
        marker = ""
        if abs(rpm - specs["max_torque_rpm"]) < 125:
            marker = "  <- T peak"
        elif abs(rpm - specs["max_power_rpm"]) < 125:
            marker = "  <- P peak"
        bar = "#" * max(0, int(torque[i] * scale))
        print(f"{rpm:5.0f} | {torque[i]:9.1f} | {heuristic.get_torque(rpm):7.1f} "
              f"| {power_kw[i]:6.1f} | {fuel[i]:8.2f} | {bar}{marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
