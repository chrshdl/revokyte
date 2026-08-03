"""Compare logged full-throttle accel runs against the engine model.

Runs are captured on-device by the dashboard's Dyno screen (the
accel-run logger) and land under ``<config dir>/accel_runs/car_<id>/``.
In a fixed gear, wheel force is proportional to acceleration, and shift
points depend only on the *shape* of the torque curve — so no vehicle
mass or drag constant is needed: everything is compared normalized to
its own peak.

Per run: samples with visible tyre slip are dropped (wheel ground speed
vs body speed), speed is smoothed, differentiated, and binned by rpm;
runs are combined per gear by the median. The result is printed next to
the calibrated engine model's WOT curve and the old heuristic, both
normalized the same way.

Caveat: aerodynamic drag rises with speed within a pull, which reads as
extra droop at the top of the measured curve — prefer low-gear runs, and
treat small measured-vs-model gaps at the very top with suspicion.

Usage (from repo root, venv active):

    python tools/engine_sim/analyze_accel.py --car-id 3231
    python tools/engine_sim/analyze_accel.py --car-id 3231 --runs-dir /path/to/accel_runs
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from instrument_cluster.core.engine_sim.accel_recorder import default_runs_dir  # noqa: E402
from instrument_cluster.core.engine_sim.engine import EngineSimulator  # noqa: E402
from instrument_cluster.core.engine_sim.params import EngineParams  # noqa: E402
from instrument_cluster.core.vehicle.ecu import EngineModel  # noqa: E402

CARS_PATH = REPO / "src" / "instrument_cluster" / "db" / "cars.json"
ARTIFACT_PATH = REPO / "src" / "instrument_cluster" / "db" / "engine_params.json"

_RPM_BIN = 250.0
_SLIP_FRACTION = 0.08  # wheel vs body speed mismatch that flags wheelspin
_SMOOTH_WINDOW = 7  # samples (~0.12 s at 60 Hz)


def _load_runs(runs_dir: Path, car_id: str) -> list[dict]:
    car_dir = runs_dir / f"car_{car_id}"
    runs = []
    for path in sorted(car_dir.glob("run_*.json")):
        with open(path, encoding="utf-8") as f:
            runs.append(json.load(f))
    return runs


def _accel_by_rpm(run: dict) -> dict[float, list[float]]:
    """rpm-bin -> acceleration samples for one run, slip filtered."""
    samples = run["samples"]
    t = np.array([s["t"] for s in samples])
    v = np.array([s["v"] for s in samples])
    rpm = np.array([s["rpm"] for s in samples])

    keep = np.ones(len(samples), dtype=bool)
    if "ws" in samples[0]:
        ws = np.array([s["ws"] for s in samples])  # (n, 4)
        with np.errstate(divide="ignore", invalid="ignore"):
            slip = np.max(np.abs(ws - v[:, None]), axis=1) / np.maximum(v, 1.0)
        keep &= (v < 3.0) | (slip < _SLIP_FRACTION)

    if len(v) >= _SMOOTH_WINDOW:
        kernel = np.ones(_SMOOTH_WINDOW) / _SMOOTH_WINDOW
        v = np.convolve(v, kernel, mode="same")
    accel = np.gradient(v, t)

    # Trim the smoothing edge artifacts.
    edge = _SMOOTH_WINDOW // 2
    keep[:edge] = False
    keep[-edge or len(keep):] = False

    bins: dict[float, list[float]] = {}
    for r, a, ok in zip(rpm, accel, keep):
        if ok and a > 0.0:
            bins.setdefault(round(r / _RPM_BIN) * _RPM_BIN, []).append(float(a))
    return bins


def _normalized(curve: np.ndarray) -> np.ndarray:
    peak = np.nanmax(curve)
    return curve / peak if peak > 0 else curve


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--car-id", required=True)
    parser.add_argument("--runs-dir", type=Path, default=None)
    parser.add_argument("--gear", type=int, default=None,
                        help="only use runs captured in this gear")
    args = parser.parse_args()

    runs_dir = args.runs_dir or default_runs_dir()
    runs = _load_runs(runs_dir, args.car_id)
    if args.gear is not None:
        runs = [r for r in runs if r["header"]["gear"] == args.gear]
    if not runs:
        print(f"no runs for car {args.car_id} under {runs_dir} — "
              "log some with the dashboard's Dyno screen first")
        return 1

    cars = json.load(open(CARS_PATH, encoding="utf-8"))
    artifact = json.load(open(ARTIFACT_PATH, encoding="utf-8"))
    specs = cars[args.car_id]

    # Combine all runs (median per rpm bin).
    combined: dict[float, list[float]] = {}
    for run in runs:
        for rpm_bin, values in _accel_by_rpm(run).items():
            combined.setdefault(rpm_bin, []).extend(values)
    rpm_axis = np.array(sorted(combined))
    measured = np.array([np.median(combined[r]) for r in rpm_axis])
    measured_n = _normalized(measured)

    heuristic = EngineModel(
        specs["max_power_kw"], specs["max_power_rpm"],
        specs["max_torque_nm"], specs["max_torque_rpm"], specs["redline_rpm"],
    )
    heur = np.array([heuristic.get_torque(r) for r in rpm_axis])
    heur_n = _normalized(heur)

    entry = artifact.get(args.car_id)
    model_n = None
    if entry and entry["fit"] == "ok":
        sim = EngineSimulator(EngineParams.from_dict(entry["params"]))
        model_n = _normalized(sim.simulate_wot(rpm_axis))

    gears = sorted({r["header"]["gear"] for r in runs})
    print(f"{specs['name']} — {len(runs)} run(s), gear(s) {gears}, "
          f"{int(rpm_axis[0])}-{int(rpm_axis[-1])} rpm")
    print("normalized to each curve's own peak (shape comparison — "
          "shift points depend only on shape)\n")
    header = "  rpm | measured | model  | heuristic"
    print(header)
    for i, r in enumerate(rpm_axis):
        model_s = f"{model_n[i]:6.3f}" if model_n is not None else "   -  "
        print(f"{r:5.0f} |   {measured_n[i]:6.3f} | {model_s} | {heur_n[i]:9.3f}")

    def rms(a, b):
        return float(np.sqrt(np.nanmean((a - b) ** 2)))

    print(f"\nshape RMS vs measured:  heuristic {rms(heur_n, measured_n):.4f}", end="")
    if model_n is not None:
        print(f"   model {rms(model_n, measured_n):.4f}")
    else:
        print("   (no calibrated model for this car)")
    print(f"measured peak at ~{int(rpm_axis[np.argmax(measured_n)])} rpm, "
          f"DB says {specs['max_torque_rpm']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
