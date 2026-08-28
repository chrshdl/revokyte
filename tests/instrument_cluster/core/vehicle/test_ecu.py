"""Shift-light ECU tests: the omit-never-null wire convention must not
crash the controller, and wire-supplied shift-point data must drive it."""

import pytest

from instrument_cluster.core.vehicle.ecu import (
    EngineModel,
    ShiftLightController,
    power_droop_for,
)
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


# A Ferrari 296 GT3 '23 (car id 3588) as cars.json describes it — peak figures
# confirmed against the game — plus a plausible GT3 sequential gearbox.
_GT3_SPECS = dict(
    name="296 GT3 '23",
    max_power_kw=447,
    max_power_rpm=6800,
    max_torque_nm=713,
    max_torque_rpm=5500,
    redline_rpm=7800,
)
_GT3_RATIOS = [2.91, 2.10, 1.68, 1.39, 1.18, 1.00]
_GT3_LIMITER = 8200


def _settled(controller, frame, frames: int = 4):
    """Run enough frames to fill the 3-deep median filter."""
    result = None
    for _ in range(frames):
        result = controller.calculate_lights(frame, 0.016)
    return result


def test_a_flat_power_engine_shifts_at_the_limiter():
    """Regression: car 3588 (Ferrari 296 GT3 '23) blinked full red at 7067 rpm
    on a car that pulls to ~8200 — 1133 rpm early, with the first green LED
    lighting at 5467. The cause was ``get_torque``'s unclamped ``dist**2``
    compounding past the power peak, which had the model believing the engine
    made half its peak power at the limiter."""
    controller = ShiftLightController(**_GT3_SPECS)
    _settled(
        controller,
        _frame(
            engine_rpm=6000.0,
            current_gear=3,
            gear_ratios=_GT3_RATIOS,
            rpm_alert=Bounds(min=7700, max=_GT3_LIMITER),
        ),
    )
    assert controller.target_rpm >= 0.93 * _GT3_LIMITER


def test_a_peaky_engine_still_shifts_early():
    """The other side of the same knob. An engine that genuinely falls off a
    cliff past its power peak must keep shifting well before the limiter —
    otherwise the shift-cost margin has simply flattened every car and the
    power curve has stopped saying anything."""
    controller = ShiftLightController(
        name="peaky",
        max_power_kw=220,
        max_power_rpm=6000,
        max_torque_nm=500,
        max_torque_rpm=4000,
        redline_rpm=6800,
    )
    _settled(
        controller,
        _frame(
            engine_rpm=5000.0,
            current_gear=3,
            gear_ratios=[3.5, 2.2, 1.6, 1.25, 1.0, 0.85],
            rpm_alert=Bounds(min=6300, max=6800),
        ),
    )
    assert controller.target_rpm <= 0.94 * 6800


def test_the_shift_target_is_anchored_on_the_limiter_not_the_rev_warning():
    """``rpm_alert.min`` is where the *game* starts warning, ~500 rpm under the
    limiter. The target used to be clamped to it, which on the no-ratios path
    (demo mode, the ACC broadcast feed) meant blinking full red at 81% of the
    limiter."""
    controller = _controller()
    _settled(
        controller,
        _frame(gear_ratios=None, engine_rpm=6000.0, rpm_alert=Bounds(min=6500, max=8000)),
    )
    assert controller.target_rpm > 6500
    assert controller.target_rpm >= 0.97 * 8000


def test_the_game_rev_warning_alone_does_not_blink():
    """``rev_limiter_alert_active`` turns on at ``rpm_alert.min`` — a warning
    band, which our own per-gear ladder already draws. Letting it force the
    alert is what skipped the 4th LED pair and forced the target down to
    compensate."""
    controller = _controller()
    leds, alert, _, _ = _settled(
        controller,
        _frame(
            engine_rpm=5000.0,
            flags=Flags(car_on_track=True, in_gear=True, rev_limiter_alert_active=True),
        ),
    )
    assert alert is False
    assert not any(leds)


def test_all_four_pairs_light_before_the_alert():
    """Guards what the rpm_alert.min clamp was protecting, now that the clamp
    is gone: sweeping up to the target must walk the ladder 0..4 and only then
    go to full blink, in every gear."""
    for gear in range(1, 6):
        controller = ShiftLightController(**_GT3_SPECS)
        seen, alerted_at = set(), None
        for rpm in range(4000, _GT3_LIMITER + 1, 25):
            leds, alert, _, _ = controller.calculate_lights(
                _frame(
                    engine_rpm=float(rpm),
                    current_gear=gear,
                    gear_ratios=_GT3_RATIOS,
                    rpm_alert=Bounds(min=7700, max=_GT3_LIMITER),
                ),
                0.016,
            )
            if alert:
                alerted_at = rpm
                break
            seen.add(sum(leds) // 2)
        assert alerted_at is not None, f"gear {gear} never reached the alert"
        assert seen == {0, 1, 2, 3, 4}, f"gear {gear} skipped a pair: {sorted(seen)}"


def test_the_curve_shape_does_not_depend_on_the_redline():
    """cars.json's ``redline_rpm`` is fabricated — every row is exactly
    ``max_power_rpm + 1000`` — and on the no-rpm_alert path it is all the
    controller has. The falloff past the power peak used to be spread over
    ``redline - max_power_rpm``, so that invented number reshaped a real car's
    curve; it is now anchored on ``max_power_rpm`` alone."""
    low = EngineModel(447, 6800, 713, 5500, 7800)
    high = EngineModel(447, 6800, 713, 5500, 9800)
    # Sampled below both redlines, so only the falloff *shape* is compared.
    for rpm in (5000, 6800, 7000, 7400, 7700):
        assert low.get_torque(rpm) == high.get_torque(rpm), f"diverged at {rpm} rpm"


def test_the_alert_survives_limiter_bounce():
    """Guards the raised exit hysteresis and the blink-phase remainder, which
    together became load-bearing once ``rev_limiter_alert_active`` stopped
    latching the alert on: bouncing off the limiter must read as a steady
    blink, not a solid bar."""
    controller = _controller()
    states = []
    for i in range(40):
        rpm = 8000.0 if i % 2 else 7850.0
        leds, alert, _, _ = controller.calculate_lights(
            _frame(engine_rpm=rpm, rpm_alert=Bounds(min=7600, max=8000)), 0.016
        )
        states.append((alert, any(leds)))
    settled = states[4:]
    assert all(alert for alert, _ in settled), "alert dropped out mid-bounce"
    assert len({lit for _, lit in settled}) == 2, "bar never blinked"


def test_the_ladder_reads_the_same_in_every_gear():
    """Regression, found on track: at 7000 rpm on a car limited to 8000 the bar
    showed two pairs in 1st, one in 3rd and nothing in 5th. The ladder was
    sized from the gear ratio, but the driver reads it against a tach that does
    not change with gear — and with ``power_to_limiter`` the shift point is the
    same rpm in every gear, so the ladder must be too."""
    controller = ShiftLightController(**{**_GT3_SPECS, "power_to_limiter": True})
    lit = {}
    for gear in range(1, 6):
        _settled(
            controller,
            _frame(
                engine_rpm=7000.0,
                current_gear=gear,
                gear_ratios=_GT3_RATIOS,
                rpm_alert=Bounds(min=7700, max=_GT3_LIMITER),
            ),
        )
        thresholds = controller._thresholds_by_gear[gear]
        lit[gear] = sum(1 for t in thresholds if t <= 7000)

    assert len(set(lit.values())) == 1, f"same rpm, different bar per gear: {lit}"
    assert lit[1] >= 2, "ladder is still bunched against the limiter"


def test_the_blink_lead_still_follows_the_gearbox():
    """The one thing that must stay gear-dependent: the blink is a cue to act,
    and rpm climbs ~4x faster in 1st than in 4th, so the lead has to be bigger
    down low or reacting to it overshoots into the limiter."""
    controller = ShiftLightController(**{**_GT3_SPECS, "power_to_limiter": True})
    for gear in range(1, 5):
        _settled(
            controller,
            _frame(
                engine_rpm=7000.0,
                current_gear=gear,
                gear_ratios=_GT3_RATIOS,
                rpm_alert=Bounds(min=7700, max=_GT3_LIMITER),
            ),
        )
    leads = {g: controller._shift_rpm_by_gear[g] - controller._alert_rpm_by_gear[g]
             for g in range(1, 5)}
    assert leads[1] > leads[2] > leads[3] > leads[4], leads

    # ...and the last pair must still land under the blink, not above it.
    for gear in range(1, 5):
        assert controller._thresholds_by_gear[gear][-1] < controller._alert_rpm_by_gear[gear]


def test_a_bogus_ratio_pair_falls_back_instead_of_inverting_the_ladder():
    """GT7 reads eight ratio slots and stops at the first zero, but some
    seven-speed layouts hold an unrelated float in the eighth. A pair that does
    not shorten the drivetrain would yield a zero or negative corridor."""
    controller = ShiftLightController(**_GT3_SPECS)
    _settled(
        controller,
        _frame(
            engine_rpm=6000.0,
            current_gear=1,
            gear_ratios=[1.0, 1.2],  # "next" gear is taller — not a real pair
            rpm_alert=Bounds(min=7700, max=_GT3_LIMITER),
        ),
    )
    pairs = controller._thresholds_by_gear[1]
    assert pairs == sorted(pairs)
    assert pairs[-1] - pairs[0] >= 400


def test_a_changed_limiter_rebuilds_the_curve():
    """The curve is scanned relative to the redline, but the rebuild used to
    trigger on gear ratios alone — so a limiter arriving after the ratios, or a
    retuned car keeping its stock gearbox, left a stale curve in place."""
    controller = ShiftLightController(**_GT3_SPECS)
    _settled(
        controller,
        _frame(engine_rpm=6000.0, gear_ratios=_GT3_RATIOS, rpm_alert=Bounds(min=7700, max=8200)),
    )
    first = controller.calculator

    # Dropped well below the curve's own optimum, so the limiter is what binds.
    _settled(
        controller,
        _frame(engine_rpm=5000.0, gear_ratios=_GT3_RATIOS, rpm_alert=Bounds(min=6300, max=6800)),
    )
    assert controller.calculator is not first
    assert controller._built_redline == 6800
    assert controller.target_rpm <= 6800


def test_a_steady_limiter_does_not_rebuild_the_curve():
    """The rebuild scans 250 rpm points per gear; a jittery wire value must not
    make that a per-frame cost on the Pi."""
    controller = ShiftLightController(**_GT3_SPECS)
    frame = _frame(engine_rpm=6000.0, gear_ratios=_GT3_RATIOS, rpm_alert=Bounds(min=7700, max=8200))
    _settled(controller, frame)
    built = controller.calculator
    for _ in range(30):
        controller.calculate_lights(frame, 0.016)
    assert controller.calculator is built


# --- engine class -> power falloff ---------------------------------------
#
# The four peak numbers a sender can put on the wire do not say how fast
# power falls away past the peak, and that is what the shift point mostly
# depends on. The class table (db/car_classes.json) is where that comes from.


def test_the_aspiration_split_is_the_measured_one():
    """Every value in the table is now a measurement, and they order the way
    the measurements did: a race engine is flat, a turbo road car very nearly
    so, and a naturally aspirated one droops. That is the opposite of the
    intuition the first priors encoded — GT7 does not model a small turbo
    falling off a cliff — so the ordering is worth pinning."""
    race = power_droop_for("NA", "race")
    turbo = power_droop_for("TC", "street")
    na = power_droop_for("NA", "street")

    assert race == 0.0
    assert race < turbo < na
    assert na < 1.0  # measured 0.62; nothing here is a cliff


def test_a_supercharger_is_read_as_forced_induction():
    """No supercharged car has been driven, so rather than invent a number
    the class inherits the measured turbo one — a blower makes boost with
    rpm, which puts it with the turbos and not the NA engines."""
    assert power_droop_for("SC", "street") == power_droop_for("TC", "street")


def test_the_measured_classes_keep_what_was_measured():
    """Two classes are no longer guesses, and a change to either should be
    a change someone made on purpose against new data:

    * race — car 3588, 9 pulls, best fit droop 0.00
    * turbo street — car 1461, 11 pulls, best fit droop 0.08-0.25
    * NA street — car 3487, 5 pulls, best fit droop 0.62
    """
    assert power_droop_for("TC", "race") == 0.0
    assert power_droop_for("TC", "street") < 0.2
    assert 0.4 < power_droop_for("NA", "street") < 0.8


def test_a_race_car_holds_power_to_the_limiter():
    """Every purpose-built racer is BOP'd flat, whatever it breathes
    through — car 3588 is a turbocharged Gr.3 and must not be read as a
    peaky road turbo."""
    assert power_droop_for("TC", "race") == 0.0
    assert power_droop_for("NA", "race") == 0.0


def test_an_unknown_class_keeps_the_historical_curve():
    """Other games' feeds have no entry in a GT7-keyed table, and that is
    not an error: they must land on exactly the falloff every car used
    before the classes existed."""
    assert power_droop_for(None, None) == pytest.approx(0.5)
    assert power_droop_for("", "") == pytest.approx(0.5)


def test_an_ev_never_droops():
    """Single-speed: there is no upshift to compute, so the curve decides
    nothing — and an electric motor has no over-rev region to model."""
    assert power_droop_for("EV", "street") == 0.0


def test_the_falloff_moves_the_shift_point():
    """The knob is only worth having if it reaches the shift point: the same
    peaks and gearbox, given an engine that falls off a cliff, must shift
    earlier than one on the default curve. Stated as an explicit droop
    rather than a class, so re-measuring a class cannot silently turn this
    into a test of nothing."""
    specs = dict(
        name="S13",
        max_power_kw=128,
        max_power_rpm=6500,
        max_torque_nm=225,
        max_torque_rpm=4000,
        redline_rpm=8000,
    )
    ratios = [3.321, 1.902, 1.308, 1.000, 0.759]
    frame = _frame(
        engine_rpm=6400.0,
        current_gear=3,
        gear_ratios=ratios,
        rpm_alert=Bounds(min=7000, max=8000),
    )

    default = ShiftLightController(**specs)
    _settled(default, frame)

    peaky = ShiftLightController(**specs, power_droop=1.3)
    _settled(peaky, frame)

    assert peaky.target_rpm < default.target_rpm - 400


def test_the_sender_still_overrides_the_class():
    """power_to_limiter is the sender saying it knows this engine. The table
    only knows the class, so the flag wins — a tuned road car with a race
    engine must not be dragged back down by its street classification."""
    engine = EngineModel(
        128, 6500, 225, 4000, 8000, power_to_limiter=True, power_droop=0.8
    )
    assert engine.power_droop == 0.0


# --- learning the real rev limiter ---------------------------------------


def _pull_to(controller, top_rpm: float, then_rpm: float, throttle: float,
             full_throttle: float = 1.0, gear: int = 2):
    """Rev to `top_rpm` at full throttle, then present `then_rpm` with
    `throttle` on the pedal — the two cases the learner must tell apart."""
    for rpm in range(4000, int(top_rpm) + 1, 50):
        _settled(
            controller,
            _frame(engine_rpm=float(rpm), current_gear=gear, throttle=full_throttle,
                   rpm_alert=Bounds(min=7000, max=8000)),
            frames=1,
        )
    _settled(
        controller,
        _frame(engine_rpm=then_rpm, current_gear=gear, throttle=throttle,
               rpm_alert=Bounds(min=7000, max=8000)),
        frames=3,
    )


def test_the_rev_limiter_is_learned_from_the_engine_itself():
    """GT7's rpm_alert.max is a tachometer value, not the fuel cut: car 1461
    declares 8000 and cuts at ~7215, measured over three pulls. Anchored on
    the declared number the target sits above anything the engine can reach,
    so the ladder never finishes and the blink never fires."""
    controller = _controller()
    before = _settled(controller, _frame(engine_rpm=6000.0, current_gear=2)) and None
    _pull_to(controller, top_rpm=7200, then_rpm=7000.0, throttle=1.0)

    assert controller._observed_limiter is not None
    assert 7100 <= controller._observed_limiter <= 7200
    _settled(controller, _frame(engine_rpm=6000.0, current_gear=2))
    assert controller.target_rpm <= 7200


def test_a_lift_is_not_a_rev_limiter():
    """Rpm falls every time the driver lifts. Only rpm falling *while the
    pedal is down* is the engine refusing to rev."""
    controller = _controller()
    _pull_to(controller, top_rpm=7200, then_rpm=7000.0, throttle=0.2)

    assert controller._observed_limiter is None


def test_a_stumble_far_below_the_limit_is_not_a_rev_limiter():
    """Wheelspin hooking up, a missed gear or a bad frame all drop rpm at
    full throttle. Believing one would peg the shift point far too low."""
    controller = _controller()
    _pull_to(controller, top_rpm=5500, then_rpm=5000.0, throttle=1.0)

    assert controller._observed_limiter is None


def test_a_raw_byte_throttle_still_reads_as_the_pedal():
    """The GT7 feed emits throttle as raw 0-255 (PROTOCOL.md's deviation
    table). Taken at face value every lift looks like full throttle, and
    every lift would then teach a false limiter."""
    controller = _controller()
    _pull_to(controller, top_rpm=7200, then_rpm=7000.0, throttle=30.0,
             full_throttle=255.0)

    assert controller._observed_limiter is None


def test_a_higher_cut_supersedes_a_lower_one():
    """A first cut learned low — a cold engine, a soft limiter, a fluke —
    must not hold the shift point down forever."""
    controller = _controller()
    _pull_to(controller, top_rpm=6800, then_rpm=6600.0, throttle=1.0)
    first = controller._observed_limiter
    _pull_to(controller, top_rpm=7600, then_rpm=7400.0, throttle=1.0)

    assert first is not None and controller._observed_limiter > first
