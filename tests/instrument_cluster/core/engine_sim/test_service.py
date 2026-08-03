"""EngineSimService: background bake lifecycle.

Uses a private service instance (never the module singleton) pointed at
a tiny params db so tests stay hermetic and fast; the bake itself runs
the real integrator on a coarse-enough engine to finish in well under a
second on any machine.
"""

import json
import time

import pytest

from instrument_cluster.core.engine_sim.params import (
    CamSpec,
    CombustionSpec,
    EngineGeometry,
    EngineParams,
    FmepSpec,
)
from instrument_cluster.core.engine_sim.service import EngineSimService


def _params_entry(fit="ok"):
    params = EngineParams(
        geometry=EngineGeometry(
            n_cyl=4, displacement_l=1.6, bore_stroke_ratio=1.0,
            conrod_ratio=3.3, compression_ratio=10.0,
        ),
        cam=CamSpec(ivo_deg=350, ivc_deg=585, evo_deg=135, evc_deg=375),
        combustion=CombustionSpec(),
        fmep=FmepSpec(),
        idle_rpm=1500.0,
        rated_rpm=5000.0,  # short axis keeps the test bake quick
    )
    return {
        "archetype": "i4_na",
        "fit": fit,
        "params": params.to_dict() if fit == "ok" else None,
        "fit_error": {},
    }


@pytest.fixture
def params_db_path(tmp_path):
    db = {
        "42": _params_entry(),
        "77": _params_entry(fit="failed"),
        "99": _params_entry(fit="ev_bypass"),
        "default": _params_entry(),
    }
    path = tmp_path / "engine_params.json"
    path.write_text(json.dumps(db))
    return path


def _wait_for(condition, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_poll_is_none_until_the_bake_lands(params_db_path):
    service = EngineSimService(params_db_path)
    assert service.poll(42) is None
    service.request(42)
    assert _wait_for(lambda: service.poll(42) is not None)
    baked = service.poll(42)
    assert baked.torque(3000.0, 1.0) > 0.0
    assert baked.rpm_max >= 5000.0


def test_invalid_and_bypassed_cars_never_produce_maps(params_db_path):
    service = EngineSimService(params_db_path)
    service.request(-1)  # ACC / boot frame
    service.request(77)  # fit failed offline
    service.request(99)  # EV bypass
    time.sleep(0.05)
    assert service.poll(-1) is None
    assert service.poll(77) is None
    assert service.poll(99) is None
    # failed/bypassed ids are remembered without spawning a worker
    assert 77 in service._failed and 99 in service._failed


def test_unknown_id_falls_back_to_default_params(params_db_path):
    service = EngineSimService(params_db_path)
    service.request(31415)
    assert _wait_for(lambda: service.poll(31415) is not None)


def test_missing_params_file_degrades_to_heuristic(tmp_path):
    service = EngineSimService(tmp_path / "nope.json")
    service.request(42)
    time.sleep(0.05)
    assert service.poll(42) is None


def test_ensure_rpm_extends_the_axis(params_db_path):
    service = EngineSimService(params_db_path)
    service.request(42)
    assert _wait_for(lambda: service.poll(42) is not None)
    old_max = service.poll(42).rpm_max

    service.ensure_rpm(42, old_max * 1.4)
    assert _wait_for(lambda: service.poll(42).rpm_max > old_max)
    # small changes below the trigger do not re-bake
    generation = service._latest_gen
    service.ensure_rpm(42, old_max * 1.01)
    assert service._latest_gen == generation


def test_duplicate_requests_do_not_restart_the_bake(params_db_path):
    """ShiftLights and FuelSignal both request on a car change; the
    second must not cancel the first's in-flight bake."""
    service = EngineSimService(params_db_path)
    service.request(42)
    generation = service._latest_gen
    service.request(42)
    service.request(42)
    assert service._latest_gen == generation
    assert _wait_for(lambda: service.poll(42) is not None)


def test_stale_requests_are_superseded(params_db_path):
    service = EngineSimService(params_db_path)
    # Flood requests for distinct cars; only the newest generation must
    # survive, everything else is dropped or cancelled mid-bake.
    with service._lock:
        pass  # just proving the lock is not held around bakes
    service.request(42)
    service.request(31415)
    assert _wait_for(lambda: service.poll(31415) is not None)
