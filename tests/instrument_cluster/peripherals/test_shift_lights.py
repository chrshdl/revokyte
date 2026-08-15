"""ShiftLights spec precedence: wire engine → cars.json → default profile."""

from instrument_cluster.core.vehicle.vehicle_bus import VehicleBus
from instrument_cluster.peripherals.shift_lights import ShiftLights
from instrument_cluster.telemetry.models import (
    Bounds,
    Engine,
    Flags,
    TelemetryFrame,
)


def _bus(frame: TelemetryFrame) -> VehicleBus:
    bus = VehicleBus()
    bus.update_frame(frame)
    return bus


def _frame(**overrides) -> TelemetryFrame:
    fields = {
        "car_id": 24,  # exists in cars.json as the GT7 180SX
        "engine_rpm": 5000.0,
        "current_gear": 2,
        "flags": Flags(car_on_track=True, in_gear=True),
        "gear_ratios": [3.2, 2.4, 1.9],
        "rpm_alert": Bounds(min=8300, max=8800),
    }
    fields.update(overrides)
    return TelemetryFrame(**fields)


_WIRE_ENGINE = Engine(
    max_power_kw=380.0,
    max_power_rpm=7200.0,
    max_torque_nm=650.0,
    max_torque_rpm=5500.0,
)


def test_wire_engine_wins_over_the_local_database():
    """A sender that knows its car (e.g. the ACC agent) must not be
    second-guessed by the GT7 database — id 24 means a different car in
    every game's id space."""
    lights = ShiftLights()
    lights.update(_bus(_frame(engine=_WIRE_ENGINE)), 0.016)

    engine = lights.controller.engine
    assert engine.max_power_rpm == 7200.0
    assert engine.max_torque_nm == 650.0
    assert engine.redline == 8800  # from rpm_alert, not the database


def test_absent_engine_falls_back_to_the_database():
    lights = ShiftLights()
    lights.update(_bus(_frame()), 0.016)

    # cars.json id 24 (180SX): 151 kW @ 6000, redline updated per frame.
    assert lights.controller.engine.max_power_rpm == 6000
    assert lights.controller.engine.max_torque_nm == 274


def test_engine_change_rebuilds_the_controller():
    """The ACC agent's learned/table specs can change mid-session (car
    swap in an open lobby): same car_id field semantics, new curve."""
    lights = ShiftLights()
    lights.update(_bus(_frame(engine=_WIRE_ENGINE)), 0.016)
    first = lights.controller

    revised = _WIRE_ENGINE.model_copy(update={"max_torque_rpm": 6000.0})
    lights.update(_bus(_frame(engine=revised)), 0.016)

    assert lights.controller is not first
    assert lights.controller.engine.max_torque_rpm == 6000.0


def test_stable_specs_do_not_rebuild_per_frame():
    lights = ShiftLights()
    frame = _frame(engine=_WIRE_ENGINE)
    lights.update(_bus(frame), 0.016)
    first = lights.controller
    lights.update(_bus(frame), 0.016)
    assert lights.controller is first


def test_disabled_toggle_blanks_the_bar_once_and_stays_silent(monkeypatch):
    """config.shift_lights off: the bar is blanked on the off-edge (never
    left frozen mid-pattern) and gets no further SPI traffic — the
    controller isn't even consulted."""
    from instrument_cluster.config import ConfigManager

    lights = ShiftLights()
    bus = _bus(_frame())
    # A lit bar, however it got that way (mid-pattern state).
    lights._render_cache = [(255, 0, 0)] * lights.ledbar.NUM_PIXELS

    monkeypatch.setattr(ConfigManager.get_config(), "shift_lights", False)
    resets = []
    monkeypatch.setattr(lights.ledbar, "reset", lambda: resets.append(True))
    lights.update(bus, 0.016)
    assert resets == [True]  # blanked exactly once
    assert all(c == (0, 0, 0) for c in lights._render_cache)
    lights.update(bus, 0.016)
    assert resets == [True]  # ...and then silence
    assert lights.controller is None  # never consulted while disabled


def test_reenabled_toggle_resumes_rendering(monkeypatch):
    from instrument_cluster.config import ConfigManager

    lights = ShiftLights()
    bus = _bus(_frame())
    cfg = ConfigManager.get_config()
    monkeypatch.setattr(cfg, "shift_lights", False)
    lights.update(bus, 0.016)
    assert lights.controller is None
    monkeypatch.setattr(cfg, "shift_lights", True)
    lights.update(bus, 0.016)
    # The full path ran again: controller built from the frame's specs.
    assert lights.controller is not None


def test_stale_telemetry_blanks_the_bar_once(monkeypatch):
    """A dead link (mode switch, crashed feed, sleeping console) must not
    leave the bar frozen mid-pattern: readers hold their last frame
    forever, so the stale flag is the only truth about liveness."""
    lights = ShiftLights()
    bus = _bus(_frame())
    lights._render_cache = [(255, 0, 0)] * lights.ledbar.NUM_PIXELS

    bus.signals["telemetry_stale"] = True
    resets = []
    monkeypatch.setattr(lights.ledbar, "reset", lambda: resets.append(True))
    lights.update(bus, 0.016)
    assert resets == [True]  # blanked exactly once
    lights.update(bus, 0.016)
    assert resets == [True]  # ...and then silence
    assert lights.controller is None  # never consulted while stale


def test_fresh_telemetry_resumes_after_stale(monkeypatch):
    lights = ShiftLights()
    bus = _bus(_frame())
    bus.signals["telemetry_stale"] = True
    lights.update(bus, 0.016)
    assert lights.controller is None
    bus.signals["telemetry_stale"] = False
    lights.update(bus, 0.016)
    assert lights.controller is not None
