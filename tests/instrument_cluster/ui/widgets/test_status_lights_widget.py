from dataclasses import dataclass, field

import pytest

from instrument_cluster.ui.widgets.status_lights_widget import StatusLightsWidget


@dataclass
class MockFlags:
    tcs_active: bool = False
    asm_active: bool = False


@dataclass
class MockTelemetryFrame:
    flags: MockFlags = field(default_factory=MockFlags)


@dataclass
class MockVehicleBus:
    frame: MockTelemetryFrame = field(default_factory=MockTelemetryFrame)
    signals: dict = field(default_factory=dict)


# --- Fixtures ---


@pytest.fixture
def bus():
    return MockVehicleBus()


@pytest.fixture
def lights():
    return StatusLightsWidget(rect=(0, 173, 50, 224))


# --- State Tests ---


def test_starts_unlit(lights):
    assert lights._last_state == (False, False)


def test_tc_flag_lights_tc(lights, bus):
    bus.frame.flags.tcs_active = True
    lights.update(bus, dt=0.016)
    assert lights._last_state == (True, False)


def test_asm_flag_lights_asm(lights, bus):
    bus.frame.flags.asm_active = True
    lights.update(bus, dt=0.016)
    assert lights._last_state == (False, True)


def test_both_flags_light_both(lights, bus):
    bus.frame.flags.tcs_active = True
    bus.frame.flags.asm_active = True
    lights.update(bus, dt=0.016)
    assert lights._last_state == (True, True)


# --- Hold Behavior ---


def test_single_frame_intervention_holds(lights, bus):
    bus.frame.flags.tcs_active = True
    lights.update(bus, dt=0.016)

    # flag drops next frame — light must stay lit for the hold period
    bus.frame.flags.tcs_active = False
    lights.update(bus, dt=0.016)
    assert lights._last_state == (True, False)


def test_light_goes_dark_after_hold_expires(lights, bus):
    bus.frame.flags.tcs_active = True
    lights.update(bus, dt=0.016)

    bus.frame.flags.tcs_active = False
    lights.update(bus, dt=StatusLightsWidget._HOLD_S + 0.001)
    assert lights._last_state == (False, False)


# --- Dirty Handling ---


def test_state_change_marks_dirty(lights, bus):
    lights.dirty = 0
    bus.frame.flags.tcs_active = True
    lights.update(bus, dt=0.016)
    assert lights.dirty == 1

    lights.dirty = 0
    lights.update(bus, dt=0.016)  # unchanged state — no redraw
    assert lights.dirty == 0


# --- Robustness ---


def test_missing_frame_is_ignored(lights, bus):
    bus.frame.flags.tcs_active = True
    lights.update(bus, dt=0.016)

    bus.frame = None
    lights.update(bus, dt=0.016)  # no crash, state unchanged
    assert lights._last_state == (True, False)


def test_missing_flags_reads_as_inactive(lights, bus):
    bus.frame.flags = None
    lights.update(bus, dt=0.016)
    assert lights._last_state == (False, False)
