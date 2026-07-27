"""Tests for DeltaSignal using a stub DeltaCalculatorProtocol."""
from dataclasses import dataclass, field
from typing import Any

import pytest

from instrument_cluster.signals.delta_signal import DeltaSignal
from instrument_cluster.signals.signal_keys import DeltaState, SignalKey


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class StubCalculator:
    """Minimal DeltaCalculatorProtocol implementation for testing."""

    def __init__(self, return_value: float = 1.5) -> None:
        self.use_fastest_reference_only: bool = False
        self._return_value = return_value
        self.full_reset_calls: int = 0

    def process(
        self, lap_index, dt, x, y, z, running,
        gt7_lap_time_ms=None, gt7_last_lap_time_ms=None,
    ) -> float:
        return self._return_value

    def full_reset(self) -> None:
        self.full_reset_calls += 1


@dataclass
class FakeFlags:
    paused: bool = False
    loading_or_processing: bool = False
    car_on_track: bool = True


@dataclass
class FakeVector:
    x: float = 10.0
    y: float = 0.0
    z: float = 5.0


@dataclass
class FakeFrame:
    lap_count: int = 1
    flags: Any = field(default_factory=FakeFlags)
    position: Any = field(default_factory=FakeVector)
    received_time: float = field(default_factory=lambda: __import__("time").perf_counter())
    current_lap_time: int | None = 1000  # ms; GT7 master clock (Packet C)
    last_lap_time: int | None = None
    native_delta_ms: int | None = None  # set by feeds that provide their own delta


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def calc():
    return StubCalculator(return_value=0.5)


@pytest.fixture
def signal(calc):
    s = DeltaSignal()
    s.calculator = calc
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_returns_empty_when_frame_is_none(signal):
    result = signal.update(None, {}, 0.016)
    assert result == {}


def test_returns_empty_when_flags_is_none(signal):
    frame = FakeFrame(flags=None)
    result = signal.update(frame, {}, 0.016)
    assert result == {}


def test_returns_both_signal_keys(signal):
    frame = FakeFrame()
    result = signal.update(frame, {}, 0.016)
    assert SignalKey.DELTA_DIFF in result
    assert SignalKey.DELTA_DIFF_STABLE in result


def test_native_delta_is_republished_and_skips_calculator(signal, calc):
    # A source-provided delta (ms) is converted to seconds and published,
    # bypassing the trajectory calculator entirely.
    calc._return_value = 99.0  # would surface if the compute path ran
    frame = FakeFrame(native_delta_ms=-1500)
    result = signal.update(frame, {}, 0.016)
    assert result[SignalKey.DELTA_DIFF] == -1.5
    assert SignalKey.DELTA_DIFF_STABLE in result
    # ACC's reference is session-best; the diff-reference-mode keys are cleared.
    assert result[SignalKey.DELTA_REF_LAP_TIME] is None
    assert result[SignalKey.DELTA_REFERENCE_MODE] is None


def test_absent_native_delta_uses_compute_path(signal, calc):
    calc._return_value = 2.0
    frame = FakeFrame(native_delta_ms=None)
    result = signal.update(frame, {}, 0.016)
    assert result[SignalKey.DELTA_DIFF] == 2.0


def test_delta_diff_matches_calculator_output(signal, calc):
    calc._return_value = 2.0
    frame = FakeFrame()
    result = signal.update(frame, {}, 0.016)
    assert result[SignalKey.DELTA_DIFF] == 2.0


def test_lap_change_resets_stable_signal(signal):
    # A lap boundary is now GT7's current_lap_time (master clock) resetting, not
    # the lap_count tick. First lap: clock near the end of the lap.
    frame = FakeFrame(lap_count=1, current_lap_time=90000)
    signal.update(frame, {}, 0.016)

    # Pretend the finished lap was long enough to clear the partial-lap gate so
    # the reference bookkeeping doesn't discard/blank the delta this frame.
    signal._lap_timer = 30.0

    # New lap: current_lap_time drops back to ~0 (the master clock reset) — this
    # is what resets the stable signal.
    frame2 = FakeFrame(lap_count=2, current_lap_time=100)
    result = signal.update(frame2, {}, 0.016)

    # After reset, stable signal forces an immediate update on next sample.
    # delta_diff_stable should be equal to the raw value (first sample after reset).
    assert result[SignalKey.DELTA_DIFF_STABLE] == result[SignalKey.DELTA_DIFF]


def test_track_change_calls_full_reset(signal, calc):
    frame = FakeFrame()
    # Prime: None → track_a triggers one reset (new track acquired).
    signal.update(frame, {SignalKey.TRACK_ID: "track_a"}, 0.016)
    assert calc.full_reset_calls == 1

    # Changing to a different track triggers another reset.
    signal.update(frame, {SignalKey.TRACK_ID: "track_b"}, 0.016)
    assert calc.full_reset_calls == 2


def test_no_full_reset_when_track_stays_none(signal, calc):
    frame = FakeFrame()
    # Track starts as None and stays None — should never call full_reset.
    signal.update(frame, {SignalKey.TRACK_ID: None}, 0.016)
    signal.update(frame, {SignalKey.TRACK_ID: None}, 0.016)
    assert calc.full_reset_calls == 0


def test_full_reset_called_when_track_becomes_known(signal, calc):
    frame = FakeFrame()
    # First call: track unknown
    signal.update(frame, {SignalKey.TRACK_ID: None}, 0.016)
    assert calc.full_reset_calls == 0

    # Second call: track identified for the first time
    signal.update(frame, {SignalKey.TRACK_ID: "nurburgring"}, 0.016)
    assert calc.full_reset_calls == 1


def test_fastest_reference_mode_sets_flag(signal, calc, tmp_path, monkeypatch):
    from instrument_cluster.config import Config, ConfigManager
    from instrument_cluster.telemetry.mode import DiffReferenceMode

    cfg = Config(diff_reference_mode=DiffReferenceMode.FASTEST.value)
    monkeypatch.setattr(ConfigManager, "get_config", classmethod(lambda cls: cfg))

    frame = FakeFrame()
    signal._last_diff_mode = None  # force re-sync
    signal.update(frame, {}, 0.016)

    assert calc.use_fastest_reference_only is True


def test_previous_reference_mode_clears_flag(signal, calc, monkeypatch):
    from instrument_cluster.config import Config, ConfigManager
    from instrument_cluster.telemetry.mode import DiffReferenceMode

    cfg = Config(diff_reference_mode=DiffReferenceMode.PREVIOUS.value)
    monkeypatch.setattr(ConfigManager, "get_config", classmethod(lambda cls: cfg))

    calc.use_fastest_reference_only = True
    frame = FakeFrame()
    signal._last_diff_mode = None
    signal.update(frame, {}, 0.016)

    assert calc.use_fastest_reference_only is False


class DualReferenceStubCalculator(StubCalculator):
    """Stub mimicking the dual-reference calculator: flipping the mode swaps
    the active reference, so the debug state reports a different identity."""

    def get_debug_state(self):
        if self.use_fastest_reference_only:
            return {"ref_version": 7, "ref_lap_time": 88.0}
        return {"ref_version": 3, "ref_lap_time": 95.0}


def test_mode_switch_mid_session_refreshes_ref_lap_time_and_stable(monkeypatch):
    """Switching the diff reference mode while driving must republish the
    swapped reference's lap time immediately and let the new delta through
    the stable filter at once — not at the next lap boundary / refresh tick."""
    from instrument_cluster.config import Config, ConfigManager
    from instrument_cluster.telemetry.mode import DiffReferenceMode

    calc = DualReferenceStubCalculator(return_value=0.5)
    signal = DeltaSignal()
    signal.calculator = calc

    cfg = Config(diff_reference_mode=DiffReferenceMode.PREVIOUS.value)
    monkeypatch.setattr(ConfigManager, "get_config", classmethod(lambda cls: cfg))

    # A few frames in PREVIOUS mode so the stable filter is holding 0.5.
    signal._last_diff_mode = None
    for _ in range(3):
        signal.update(FakeFrame(), {}, 0.016)
    signal._ref_lap_time = 95.0  # as adopted at an earlier lap boundary

    # Mid-session switch to FASTEST; the swapped reference changes the delta.
    calc._return_value = 2.0
    cfg.diff_reference_mode = DiffReferenceMode.FASTEST.value
    result = signal.update(FakeFrame(), {}, 0.016)

    assert calc.use_fastest_reference_only is True
    # Reference lap time re-read from the now-active reference…
    assert result[SignalKey.DELTA_REF_LAP_TIME] == 88.0
    # …and the stable value jumps to the new raw delta immediately instead of
    # holding 0.5 for the rest of the 200 ms refresh period.
    assert result[SignalKey.DELTA_DIFF_STABLE] == 2.0


def test_initial_mode_sync_does_not_touch_ref_lap_time(monkeypatch):
    """The first sync of a fresh signal is initialization, not a switch — it
    must not clobber reference bookkeeping."""
    from instrument_cluster.config import Config, ConfigManager
    from instrument_cluster.telemetry.mode import DiffReferenceMode

    calc = DualReferenceStubCalculator(return_value=0.5)
    signal = DeltaSignal()
    signal.calculator = calc
    signal._ref_lap_time = 42.0
    signal._last_diff_mode = None

    cfg = Config(diff_reference_mode=DiffReferenceMode.FASTEST.value)
    monkeypatch.setattr(ConfigManager, "get_config", classmethod(lambda cls: cfg))
    result = signal.update(FakeFrame(), {}, 0.016)

    assert result[SignalKey.DELTA_REF_LAP_TIME] == 42.0


def test_publishes_active_reference_mode(signal, monkeypatch):
    """The active mode is published to the bus so UI (the diff widget header)
    can name the reference the delta is computed against."""
    from instrument_cluster.config import Config, ConfigManager
    from instrument_cluster.telemetry.mode import DiffReferenceMode

    cfg = Config(diff_reference_mode=DiffReferenceMode.FASTEST.value)
    monkeypatch.setattr(ConfigManager, "get_config", classmethod(lambda cls: cfg))

    signal._last_diff_mode = None
    result = signal.update(FakeFrame(), {}, 0.016)
    assert result[SignalKey.DELTA_REFERENCE_MODE] == "fastest"

    cfg.diff_reference_mode = DiffReferenceMode.PREVIOUS.value
    result = signal.update(FakeFrame(), {}, 0.016)
    assert result[SignalKey.DELTA_REFERENCE_MODE] == "previous"


# ---------------------------------------------------------------------------
# Delta state — why the gauge has no number
# ---------------------------------------------------------------------------


class RefStateStubCalculator(StubCalculator):
    """StubCalculator with a controllable reference, so the state machine can
    be driven through every cause of a missing delta."""

    def __init__(self, return_value: float = 0.5, has_reference: bool = False):
        super().__init__(return_value=return_value)
        self.has_reference = has_reference

    def full_reset(self) -> None:
        super().full_reset()
        self.has_reference = False


def _state(signal, frame, signals=None, dt=0.016):
    return signal.update(frame, signals or {}, dt).get(SignalKey.DELTA_STATE)


def test_state_is_beacon_when_not_in_a_timed_lap():
    """lap_count 0 — nothing can be timed until the car crosses the line."""
    signal = DeltaSignal()
    signal.calculator = RefStateStubCalculator(has_reference=True)
    assert _state(signal, FakeFrame(lap_count=0)) == DeltaState.BEACON


def test_state_is_ref_lap_while_recording_the_first_reference():
    """A driver who has never had a reference is told a lap is being
    recorded — not that something was lost."""
    signal = DeltaSignal()
    signal.calculator = RefStateStubCalculator(has_reference=False)
    assert _state(signal, FakeFrame(lap_count=1)) == DeltaState.REF_LAP


def test_state_is_none_once_a_reference_exists():
    """Armed: the number is the thing to show, so no state word."""
    signal = DeltaSignal()
    signal.calculator = RefStateStubCalculator(has_reference=True)
    assert _state(signal, FakeFrame(lap_count=2)) is None


def test_losing_an_established_reference_reports_no_ref():
    """Changing circuit throws away a reference the driver had — different
    news from never having had one."""
    calc = RefStateStubCalculator(has_reference=True)
    signal = DeltaSignal()
    signal.calculator = calc

    # Arriving on a circuit clears any carry-over reference…
    signal.update(FakeFrame(lap_count=1), {SignalKey.TRACK_ID: "spa"}, 0.016)
    # …then a lap gets recorded, so the driver now has one.
    calc.has_reference = True
    assert _state(signal, FakeFrame(lap_count=2), {SignalKey.TRACK_ID: "spa"}) is None

    # A genuinely different circuit throws that reference away.
    assert (
        _state(signal, FakeFrame(lap_count=2), {SignalKey.TRACK_ID: "monza"})
        == DeltaState.NO_REF
    )
    assert calc.full_reset_calls == 2  # arrival + the change


def test_track_change_before_any_reference_still_reports_ref_lap():
    """No reference was lost, so NO REF would be a lie."""
    signal = DeltaSignal()
    signal.calculator = RefStateStubCalculator(has_reference=False)

    signal.update(FakeFrame(lap_count=1), {SignalKey.TRACK_ID: "spa"}, 0.016)
    state = _state(signal, FakeFrame(lap_count=1), {SignalKey.TRACK_ID: "monza"})
    assert state == DeltaState.REF_LAP


def test_no_ref_clears_once_a_new_reference_is_adopted():
    calc = RefStateStubCalculator(has_reference=True)
    signal = DeltaSignal()
    signal.calculator = calc

    signal.update(FakeFrame(lap_count=1), {SignalKey.TRACK_ID: "spa"}, 0.016)
    calc.has_reference = True  # a reference lap was recorded on spa
    signal.update(FakeFrame(lap_count=2), {SignalKey.TRACK_ID: "spa"}, 0.016)

    assert (
        _state(signal, FakeFrame(lap_count=2), {SignalKey.TRACK_ID: "monza"})
        == DeltaState.NO_REF
    )

    calc.has_reference = True  # a replacement lap was recorded
    assert _state(signal, FakeFrame(lap_count=3), {SignalKey.TRACK_ID: "monza"}) is None


def test_native_delta_never_shows_a_waiting_state():
    """A feed that computes its own delta has no reference lap of ours to
    wait for (ACC via the Broadcasting API)."""
    signal = DeltaSignal()
    signal.calculator = RefStateStubCalculator(has_reference=False)
    result = signal.update(FakeFrame(native_delta_ms=-250), {}, 0.016)

    assert result[SignalKey.DELTA_STATE] is None
    assert result[SignalKey.DELTA_DIFF] == -0.25


def test_state_survives_a_calculator_without_the_property():
    """An external/fallback calculator may not expose has_reference; the
    gauge must degrade to 'waiting', not crash."""
    signal = DeltaSignal()
    signal.calculator = StubCalculator(return_value=0.5)  # no has_reference
    assert _state(signal, FakeFrame(lap_count=1)) == DeltaState.REF_LAP
