"""The checked-in calibration artifact (db/engine_params.json).

These tests gate the *artifact*, not the fitter: they fail when someone
edits cars.json or the physics without regenerating via
tools/engine_sim/fit_cars.py, and they pin the accuracy contract for a
deliberately diverse car sample — including the entries that are
supposed to fail or be bypassed.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from instrument_cluster.core.engine_sim.engine import EngineSimulator
from instrument_cluster.core.engine_sim.params import EngineParams

_DB_DIR = Path(__file__).resolve().parents[4] / "src" / "instrument_cluster" / "db"

# id -> why it is in the sample
_DIVERSE_OK_SAMPLE = {
    "37": "high-revving NA VTEC",
    "31": "lazy pushrod V8",
    "24": "ordinary street NA",
    "82": "big straight six",
    "296": "rotary (787B)",
    "1965": "diesel prototype (R18 TDI)",
    "36": "big-block muscle",
    "451": "flat-torque turbo (22B)",
    "2049": "quad-turbo W16 (Veyron)",
    "1562": "V10 exotic (LFA)",
}


@pytest.fixture(scope="module")
def artifact():
    with open(_DB_DIR / "engine_params.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def cars():
    with open(_DB_DIR / "cars.json", encoding="utf-8") as f:
        return json.load(f)


def test_artifact_covers_every_car_plus_default(artifact, cars):
    missing = set(cars) - set(artifact)
    assert not missing, f"regenerate engine_params.json; missing ids: {sorted(missing)[:10]}"
    assert "default" in artifact
    assert artifact["default"]["fit"] == "ok"


def test_entries_are_schema_complete(artifact):
    for cid, entry in artifact.items():
        assert entry["fit"] in ("ok", "failed", "ev_bypass"), cid
        assert "archetype" in entry, cid
        if entry["fit"] == "ok":
            assert entry["params"], cid
            # must round-trip into EngineParams
            EngineParams.from_dict(entry["params"])
        else:
            assert entry["params"] is None, cid


def test_fit_rate_is_high(artifact):
    fits = [e["fit"] for e in artifact.values()]
    ok = fits.count("ok")
    assert ok / len(fits) >= 0.9, f"only {ok}/{len(fits)} cars fit"


def test_special_entries(artifact):
    assert artifact["1537"]["fit"] == "ev_bypass"  # Prius
    assert artifact["2026"]["fit"] == "ev_bypass"  # Aqua
    assert artifact["296"]["archetype"] == "rotary"
    assert artifact["1965"]["archetype"] == "diesel"
    assert artifact["2060"]["archetype"] == "two_stroke"
    # fictional 1928 kW monster: expected to be unfittable, and that must
    # degrade to "failed" (heuristic fallback), never crash the pipeline
    assert artifact["2108"]["fit"] in ("failed", "ok")


def test_null_name_cars_were_classified(artifact, cars):
    null_named = [cid for cid, s in cars.items() if s.get("name") is None]
    assert null_named, "fixture assumption: cars.json has null-name entries"
    for cid in null_named:
        assert cid in artifact
        assert artifact[cid]["fit"] in ("ok", "failed", "ev_bypass")


@pytest.mark.parametrize("cid", sorted(_DIVERSE_OK_SAMPLE))
def test_diverse_sample_hits_db_peaks(cid, artifact, cars):
    entry = artifact[cid]
    assert entry["fit"] == "ok", (
        f"{cars[cid]['name']} ({_DIVERSE_OK_SAMPLE[cid]}): {entry['fit_error']}"
    )
    specs = cars[cid]
    params = EngineParams.from_dict(entry["params"])
    sim = EngineSimulator(params)

    rpm_t = specs["max_torque_rpm"]
    rpm_p = specs["max_power_rpm"]
    axis = np.asarray(sorted({float(rpm_t), float(rpm_p)}))
    torque = sim.simulate_wot(axis, step_deg=1.0, max_cycles=3)

    t_model = float(np.interp(rpm_t, axis, torque))
    p_model_kw = float(np.interp(rpm_p, axis, torque)) * rpm_p * 2 * np.pi / 60 / 1e3
    assert t_model == pytest.approx(specs["max_torque_nm"], rel=0.025)
    assert p_model_kw == pytest.approx(specs["max_power_kw"], rel=0.025)
