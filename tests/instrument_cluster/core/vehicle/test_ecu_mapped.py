"""install_engine_map: the calibrated map slots under the untouched
ShiftLightController state machine.

A FakeFrame drives calculate_lights exactly like the peripheral does;
the assertions pin that the swap rebuilds the ShiftPointCalculator from
the new torque source and that shift points stay in a sane corridor
around the heuristic's (the physics should move them, not teleport them).
"""

from dataclasses import dataclass, field

import numpy as np
import pytest

from instrument_cluster.core.engine_sim.runtime_model import MappedEngineModel
from instrument_cluster.core.engine_sim.torque_map import TorqueFuelMap
from instrument_cluster.core.vehicle.ecu import EngineModel, ShiftLightController


@dataclass
class FakeBounds:
    min: float = 0.0
    max: float = 0.0


@dataclass
class FakeFlags:
    rev_limiter_alert_active: bool = False
    tcs_active: bool = False
    asm_active: bool = False


@dataclass
class FakeFrame:
    engine_rpm: float = 3000.0
    current_gear: int = 3
    gear_ratios: list = field(default_factory=lambda: [3.2, 2.1, 1.6, 1.25, 1.0])
    rpm_alert: FakeBounds = field(default_factory=FakeBounds)
    flags: FakeFlags = field(default_factory=FakeFlags)


def _controller():
    return ShiftLightController(
        max_power_kw=150,
        max_power_rpm=6500,
        max_torque_nm=200,
        max_torque_rpm=4500,
        redline_rpm=7500,
    )


def _map_from_heuristic(scale=1.0):
    """Bake the heuristic curve into map form so mapped and heuristic
    shift points are comparable."""
    engine = EngineModel(150, 6500, 200, 4500, 7500)
    rpm = np.arange(1000.0, 7900.0, 200.0)
    torque = np.array([engine.get_torque(r) * scale for r in rpm])
    grid = np.stack([torque * 0.1, torque * 0.6, torque], axis=1)
    return TorqueFuelMap(rpm, np.array([0.0, 0.5, 1.0]), grid, np.abs(grid) * 0.01)


def test_install_swaps_engine_and_forces_calculator_rebuild():
    controller = _controller()
    frame = FakeFrame()
    controller.calculate_lights(frame, 0.016)
    assert controller.calculator is not None
    old_calc = controller.calculator

    controller.install_engine_map(MappedEngineModel(_map_from_heuristic(), 7500))
    assert controller.calculator is None

    controller.calculate_lights(frame, 0.016)
    assert controller.calculator is not None
    assert controller.calculator is not old_calc
    assert isinstance(controller.engine, MappedEngineModel)


def test_installed_model_inherits_live_redline():
    controller = _controller()
    frame = FakeFrame(rpm_alert=FakeBounds(min=7000, max=8000))
    controller.calculate_lights(frame, 0.016)
    assert controller.engine.redline == 8000

    controller.install_engine_map(MappedEngineModel(_map_from_heuristic(), 999))
    # install must carry the telemetry-updated redline over, not the
    # constructor's placeholder
    assert controller.engine.redline == 8000


def test_mapped_shift_points_stay_in_corridor():
    heuristic = _controller()
    mapped = _controller()
    frame = FakeFrame()

    heuristic.calculate_lights(frame, 0.016)
    mapped.install_engine_map(MappedEngineModel(_map_from_heuristic(), 7500))
    mapped.calculate_lights(frame, 0.016)

    for gear in range(1, 5):
        h = heuristic.calculator.get_optimal_rpm(gear)
        m = mapped.calculator.get_optimal_rpm(gear)
        assert 0.7 * 7500 <= m <= 7500
        # identical curve content -> nearly identical crossover
        assert abs(m - h) <= 150.0


def test_lights_progress_toward_shift_point_with_mapped_engine():
    controller = _controller()
    controller.install_engine_map(MappedEngineModel(_map_from_heuristic(), 7500))

    low = FakeFrame(engine_rpm=2000.0)
    lights_low, alert_low, _, _ = controller.calculate_lights(low, 0.016)

    shift_rpm = controller.target_rpm
    near = FakeFrame(engine_rpm=shift_rpm - 100.0)
    # feed a few frames so the median filter catches up
    for _ in range(4):
        lights_near, _, _, _ = controller.calculate_lights(near, 0.016)

    assert sum(lights_near) > sum(lights_low)
    assert not alert_low


def test_rev_alert_still_blinks_with_mapped_engine():
    controller = _controller()
    controller.install_engine_map(MappedEngineModel(_map_from_heuristic(), 7500))
    frame = FakeFrame(
        engine_rpm=7600.0, flags=FakeFlags(rev_limiter_alert_active=True)
    )
    for _ in range(4):
        lights, is_alert, _, _ = controller.calculate_lights(frame, 0.016)
    assert is_alert
    assert all(lights) or not any(lights)  # blink phase: all on or all off
