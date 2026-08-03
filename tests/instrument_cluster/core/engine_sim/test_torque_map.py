"""TorqueFuelMap lookup semantics and MappedEngineModel's ecu surface."""

import numpy as np
import pytest

from instrument_cluster.core.engine_sim.runtime_model import MappedEngineModel
from instrument_cluster.core.engine_sim.torque_map import TorqueFuelMap


@pytest.fixture
def small_map():
    rpm = np.array([1000.0, 2000.0, 3000.0, 4000.0])
    thr = np.array([0.0, 0.5, 1.0])
    torque = np.array(
        [
            [-10.0, 60.0, 100.0],
            [-15.0, 80.0, 140.0],
            [-20.0, 90.0, 160.0],
            [-25.0, 85.0, 150.0],
        ]
    )
    fuel = np.abs(torque) * 0.01
    return TorqueFuelMap(rpm, thr, torque, fuel)


# --- TorqueFuelMap ---


def test_bilinear_exact_at_nodes(small_map):
    assert small_map.torque(2000.0, 0.5) == pytest.approx(80.0)
    assert small_map.torque(3000.0, 1.0) == pytest.approx(160.0)
    assert small_map.wot_torque(4000.0) == pytest.approx(150.0)


def test_bilinear_interpolates_between_nodes(small_map):
    # midway in rpm and throttle
    val = small_map.torque(2500.0, 0.75)
    expected = np.mean([80.0, 140.0, 90.0, 160.0])
    assert val == pytest.approx(expected)


def test_lookup_clamps_out_of_range(small_map):
    assert small_map.torque(500.0, 2.0) == pytest.approx(100.0)
    assert small_map.torque(9999.0, -1.0) == pytest.approx(-25.0)


def test_fuel_flow_floored_at_zero(small_map):
    fuel = TorqueFuelMap(
        small_map.rpm_axis,
        small_map.throttle_axis,
        small_map.torque_nm,
        small_map.fuel_g_s - 5.0,
    )
    assert fuel.fuel_flow(1000.0, 0.0) == 0.0


def test_serialization_round_trip(small_map):
    restored = TorqueFuelMap.from_dict(small_map.to_dict())
    assert np.allclose(restored.torque_nm, small_map.torque_nm)
    assert restored.torque(2500.0, 0.75) == pytest.approx(
        small_map.torque(2500.0, 0.75)
    )


# --- MappedEngineModel (the ecu-compatible facade) ---


def test_default_call_uses_wot_column(small_map):
    model = MappedEngineModel(small_map, redline=4500.0)
    assert model.get_torque(3000.0) == pytest.approx(160.0)
    assert model.get_torque(3000.0, throttle=0.5) == pytest.approx(90.0)


def test_zero_above_redline(small_map):
    model = MappedEngineModel(small_map, redline=4500.0)
    assert model.get_torque(4600.0) == 0.0


def test_over_axis_decays_from_edge_value(small_map):
    model = MappedEngineModel(small_map, redline=5000.0)
    over = model.get_torque(4500.0)
    assert 0.0 < over < 150.0
    # monotone decay toward redline
    assert model.get_torque(4900.0) < over


def test_redline_is_mutable_like_engine_model(small_map):
    model = MappedEngineModel(small_map, redline=4500.0)
    model.redline = 4200.0
    assert model.redline == 4200.0
    assert model.get_torque(4300.0) == 0.0


def test_redline_beyond_axis_triggers_extend_callback(small_map):
    calls = []
    model = MappedEngineModel(
        small_map, redline=4000.0, on_redline_extend=calls.append
    )
    model.redline = 4000.0  # unchanged -> no callback
    assert calls == []
    model.redline = 5200.0  # beyond the 4000 rpm axis
    assert calls == [5200.0]
