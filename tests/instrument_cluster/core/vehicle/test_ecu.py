"""Shift-light ECU tests: the omit-never-null wire convention must not
crash the controller, and wire-supplied shift-point data must drive it."""

from instrument_cluster.core.vehicle.ecu import ShiftLightController
from instrument_cluster.telemetry.models import Bounds, Flags, TelemetryFrame


def _controller() -> ShiftLightController:
    return ShiftLightController(
        name="test",
        max_power_kw=380,
        max_power_rpm=7200,
        max_torque_nm=650,
        max_torque_rpm=5500,
        redline_rpm=8000,
    )


def _frame(**overrides) -> TelemetryFrame:
    """An override of None *removes* the field — mirroring the wire, where
    these fields are omit-never-null and absence is what yields the default."""
    fields = {
        "engine_rpm": 6000.0,
        "current_gear": 3,
        "flags": Flags(car_on_track=True, in_gear=True),
        "gear_ratios": [3.2, 2.4, 1.9, 1.5, 1.2, 1.0],
        "rpm_alert": Bounds(min=7600, max=8000),
    }
    fields.update(overrides)
    return TelemetryFrame(**{k: v for k, v in fields.items() if v is not None})


def test_absent_rpm_alert_does_not_crash():
    """The ACC broadcast feed never sends rpm_alert (a legal omission per
    PROTOCOL.md §3.3), which reaches the controller as None. Regression:
    ``frame.rpm_alert.max`` raised AttributeError every in-gear frame."""
    controller = _controller()
    leds, alert, _, _ = controller.calculate_lights(_frame(rpm_alert=None), 0.016)
    assert len(leds) == 8  # produced a result, kept its DB redline
    assert controller.engine.redline == 8000


def test_rpm_alert_updates_the_redline():
    controller = _controller()
    controller.calculate_lights(_frame(rpm_alert=Bounds(min=8300, max=8800)), 0.016)
    assert controller.engine.redline == 8800


def test_no_gear_ratios_falls_back_to_the_redline():
    """Demo mode and the ACC broadcast feed never send gear ratios, and the
    previous 'dark, not wrong' choice meant those users saw no shift lights
    at all. Without ratios the shift point anchors on the redline: later
    than a power-curve optimum, but correct for every car."""
    # Below the ladder window: dark.
    controller = _controller()
    for _ in range(4):
        leds, alert, _, _ = controller.calculate_lights(
            _frame(gear_ratios=None, engine_rpm=4000.0), 0.016
        )
    assert leds == [False] * 8
    assert alert is False

    # Approaching the redline: part of the ladder lights.
    controller = _controller()
    for _ in range(4):
        leds, alert, _, _ = controller.calculate_lights(
            _frame(gear_ratios=None, engine_rpm=7900.0), 0.016
        )
    assert alert or any(leds)

    # At the redline: full-bar alert.
    controller = _controller()
    for _ in range(4):
        leds, alert, _, _ = controller.calculate_lights(
            _frame(gear_ratios=None, engine_rpm=8000.0), 0.016
        )
    assert alert is True


def test_ratios_light_the_ladder_near_the_shift_point():
    controller = _controller()
    frame = _frame(engine_rpm=7900.0)
    # settle the median filter
    for _ in range(4):
        leds, alert, _, _ = controller.calculate_lights(frame, 0.016)
    assert alert or any(leds)


def test_overall_ratios_give_the_same_shift_points_as_gearbox_ratios():
    """PROTOCOL.md §3.5.5: only relative ratios matter — a learned overall
    ratio table (× final drive) must be equivalent to gearbox ratios."""
    gearbox = [3.2, 2.4, 1.9, 1.5, 1.2, 1.0]
    final_drive = 3.7
    overall = [r * final_drive for r in gearbox]

    a, b = _controller(), _controller()
    a.calculate_lights(_frame(gear_ratios=gearbox), 0.016)
    b.calculate_lights(_frame(gear_ratios=overall), 0.016)
    for gear in range(1, 6):
        assert a.calculator.get_optimal_rpm(gear) == b.calculator.get_optimal_rpm(gear)
