"""Tests for FuelSignal's per-lap consumption and laps-remaining estimate."""
from dataclasses import dataclass, field
from typing import Any

import pytest

from instrument_cluster.signals.fuel_signal import FuelSignal
from instrument_cluster.signals.signal_keys import SignalKey


@dataclass
class FakeFlags:
    paused: bool = False
    loading_or_processing: bool = False
    car_on_track: bool = True


@dataclass
class FakeFrame:
    lap_count: int | None = 1
    flags: Any = field(default_factory=FakeFlags)
    received_time: float = 0.0
    current_lap_time: int | None = 1000  # ms; GT7 master clock (Packet C)
    gas_level: float = 100.0
    gas_capacity: float = 100.0
    # Read by the FuelFlowObserver; car_id -1 keeps it inert (no map).
    car_id: int = -1
    engine_rpm: float = 0.0
    throttle: float = 0.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def signal():
    return FuelSignal()


@pytest.fixture
def drive(signal):
    """Feed one frame; received_time auto-increments unless given explicitly."""
    state = {"t": 0.0}

    def _drive(signals: dict | None = None, dt: float = 0.016, **kwargs):
        state["t"] += 1.0
        kwargs.setdefault("received_time", state["t"])
        return signal.update(FakeFrame(**kwargs), signals or {}, dt)

    return _drive


def prime_full_lap(drive, signals=None, fuel: float = 100.0):
    """Drive the partial first lap and cross into lap 2, arming lap tracking.

    Leaves the signal at the start of lap 2 with `fuel` in the tank.
    """
    drive(signals, lap_count=1, current_lap_time=50_000, gas_level=fuel)
    drive(signals, lap_count=2, current_lap_time=100, gas_level=fuel)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_returns_empty_when_frame_is_none(signal):
    assert signal.update(None, {}, 0.016) == {}


def test_default_frame_publishes_explicit_nones(signal):
    # A demo → UDP switch leaves DemoFuelSignal's values on the bus while the
    # fresh UDP reader still returns its pre-connection default frame
    # (flags=None, gas_capacity=0). That frame must publish explicit Nones so
    # the widgets fall back to the placeholder instead of showing demo values.
    result = signal.update(
        FakeFrame(flags=None, gas_capacity=0.0, received_time=0.0), {}, 0.016
    )
    assert result[SignalKey.FUEL_PER_LAP] is None
    assert result[SignalKey.FUEL_USED_CURRENT_LAP] is None
    assert result[SignalKey.FUEL_LAPS_REMAINING] is None


def test_ev_publishes_explicit_nones(drive):
    result = drive(gas_capacity=0.0)
    assert result[SignalKey.FUEL_PER_LAP] is None
    assert result[SignalKey.FUEL_USED_CURRENT_LAP] is None
    assert result[SignalKey.FUEL_LAPS_REMAINING] is None


def test_car_swap_to_ev_clears_previous_samples(drive):
    # Bank a real sample with an ICE car…
    prime_full_lap(drive)
    drive(lap_count=2, current_lap_time=50_000, gas_level=97.0)
    result = drive(lap_count=3, current_lap_time=100, gas_level=94.4)
    assert result[SignalKey.FUEL_PER_LAP] is not None

    # …then swap to an EV: values must not survive on the bus.
    result = drive(gas_capacity=0.0)
    assert result[SignalKey.FUEL_PER_LAP] is None
    assert result[SignalKey.FUEL_LAPS_REMAINING] is None


# ---------------------------------------------------------------------------
# Lap banking
# ---------------------------------------------------------------------------


def test_partial_first_lap_is_not_banked(drive):
    drive(lap_count=1, current_lap_time=50_000, gas_level=100.0)
    drive(lap_count=1, current_lap_time=80_000, gas_level=98.0)
    result = drive(lap_count=2, current_lap_time=100, gas_level=97.0)
    assert result[SignalKey.FUEL_PER_LAP] is None
    assert result[SignalKey.FUEL_LAPS_REMAINING] is None


def test_full_lap_banks_consumption_and_estimates_laps(drive):
    prime_full_lap(drive, fuel=97.0)
    drive(lap_count=2, current_lap_time=50_000, gas_level=95.5)
    result = drive(lap_count=3, current_lap_time=100, gas_level=94.4)

    assert result[SignalKey.FUEL_PER_LAP] == pytest.approx(2.6)
    assert result[SignalKey.FUEL_LAPS_REMAINING] == pytest.approx(94.4 / 2.6)


def test_rolling_window_averages_last_three_laps(drive):
    prime_full_lap(drive, fuel=100.0)
    # Bank four laps consuming 2.0 / 2.5 / 3.0 / 3.5.
    fuel = 100.0
    for lap, used in ((3, 2.0), (4, 2.5), (5, 3.0), (6, 3.5)):
        drive(lap_count=lap - 1, current_lap_time=50_000, gas_level=fuel - used / 2)
        fuel -= used
        result = drive(lap_count=lap, current_lap_time=100, gas_level=fuel)

    assert result[SignalKey.FUEL_PER_LAP] == pytest.approx(3.5)
    # Window holds the last three samples: (2.5 + 3.0 + 3.5) / 3 = 3.0.
    assert result[SignalKey.FUEL_LAPS_REMAINING] == pytest.approx(fuel / 3.0)


def test_refuel_mid_lap_discards_lap_and_never_goes_negative(drive):
    prime_full_lap(drive, fuel=50.0)
    drive(lap_count=2, current_lap_time=30_000, gas_level=48.0)
    # Pit stop: tank jumps up.
    drive(lap_count=2, current_lap_time=60_000, gas_level=95.0)
    drive(lap_count=2, current_lap_time=80_000, gas_level=94.0)
    result = drive(lap_count=3, current_lap_time=100, gas_level=93.5)

    # The refuel lap must not produce a sample (least of all a negative one).
    assert result[SignalKey.FUEL_PER_LAP] is None

    # The following complete lap banks normally against the rebased level.
    drive(lap_count=3, current_lap_time=50_000, gas_level=91.5)
    result = drive(lap_count=4, current_lap_time=100, gas_level=90.9)
    assert result[SignalKey.FUEL_PER_LAP] == pytest.approx(2.6)


def test_fuel_consumption_disabled_keeps_placeholder(drive):
    prime_full_lap(drive, fuel=100.0)
    drive(lap_count=2, current_lap_time=50_000, gas_level=100.0)
    result = drive(lap_count=3, current_lap_time=100, gas_level=100.0)
    assert result[SignalKey.FUEL_PER_LAP] is None
    assert result[SignalKey.FUEL_LAPS_REMAINING] is None


def test_zero_consumption_lap_clears_existing_window(drive):
    # Bank a real sample first…
    prime_full_lap(drive, fuel=97.0)
    drive(lap_count=2, current_lap_time=50_000, gas_level=95.5)
    result = drive(lap_count=3, current_lap_time=100, gas_level=94.4)
    assert result[SignalKey.FUEL_PER_LAP] is not None

    # …then fuel use gets disabled mid-session: a full zero-consumption lap
    # must drop the stale history.
    drive(lap_count=3, current_lap_time=50_000, gas_level=94.4)
    result = drive(lap_count=4, current_lap_time=100, gas_level=94.4)
    assert result[SignalKey.FUEL_PER_LAP] is None
    assert result[SignalKey.FUEL_LAPS_REMAINING] is None


def test_race_start_banks_lap_one(drive):
    # Watched from the grid: lap_count 0 → 1 is the green light, so lap 1
    # is fully in view and banks at its line crossing — one lap earlier
    # than the join-mid-lap case.
    drive(lap_count=0, current_lap_time=None, gas_level=100.0)
    drive(lap_count=1, current_lap_time=500, gas_level=100.0)
    drive(lap_count=1, current_lap_time=50_000, gas_level=98.0)
    result = drive(lap_count=2, current_lap_time=100, gas_level=97.4)

    assert result[SignalKey.FUEL_PER_LAP] == pytest.approx(2.6)
    assert result[SignalKey.FUEL_LAPS_REMAINING] == pytest.approx(97.4 / 2.6)


def test_race_start_banks_lap_one_without_clock(drive):
    # Packet-A-only source: the 0 → 1 tick still arms lap 1, and the
    # grid-to-line segment before it is never banked.
    drive(lap_count=0, current_lap_time=None, gas_level=100.0)
    result = drive(lap_count=1, current_lap_time=None, gas_level=99.8)
    assert result[SignalKey.FUEL_PER_LAP] is None

    drive(lap_count=1, current_lap_time=None, gas_level=98.0)
    result = drive(lap_count=2, current_lap_time=None, gas_level=97.2)
    assert result[SignalKey.FUEL_PER_LAP] == pytest.approx(2.6)


def test_restart_to_grid_banks_first_lap(drive):
    prime_full_lap(drive, fuel=97.0)

    # Restart drops back to the grid (lap 0): history clears, and the
    # 0 → 1 green light re-arms lap 1 directly.
    result = drive(lap_count=0, current_lap_time=None, gas_level=100.0)
    assert result[SignalKey.FUEL_PER_LAP] is None

    drive(lap_count=1, current_lap_time=500, gas_level=100.0)
    drive(lap_count=1, current_lap_time=50_000, gas_level=98.0)
    result = drive(lap_count=2, current_lap_time=100, gas_level=97.4)
    assert result[SignalKey.FUEL_PER_LAP] == pytest.approx(2.6)


def test_lap_count_fallback_when_clock_unavailable(drive):
    # Packet-A-only source: current_lap_time is never present.
    drive(lap_count=1, current_lap_time=None, gas_level=100.0)
    drive(lap_count=2, current_lap_time=None, gas_level=100.0)  # arms tracking
    drive(lap_count=2, current_lap_time=None, gas_level=98.0)
    result = drive(lap_count=3, current_lap_time=None, gas_level=97.4)

    assert result[SignalKey.FUEL_PER_LAP] == pytest.approx(2.6)


# ---------------------------------------------------------------------------
# Live current-lap consumption
# ---------------------------------------------------------------------------


def test_live_fuel_starts_at_zero_on_first_frame(drive):
    # Joining mid-lap: the readout measures from the first seen level, so it
    # shows 0.0 immediately instead of a placeholder.
    result = drive(lap_count=1, current_lap_time=50_000, gas_level=80.0)
    assert result[SignalKey.FUEL_USED_CURRENT_LAP] == 0.0


def test_live_fuel_resets_at_line_and_refreshes_every_five_seconds(drive):
    prime_full_lap(drive, fuel=97.0)

    # 1 s into the lap: fuel already burned, but the 5 s hold keeps 0.0.
    result = drive(lap_count=2, current_lap_time=10_000, gas_level=96.5, dt=1.0)
    assert result[SignalKey.FUEL_USED_CURRENT_LAP] == 0.0

    # Past the 5 s mark: refreshes to the burn since the line.
    result = drive(lap_count=2, current_lap_time=20_000, gas_level=96.2, dt=4.1)
    assert result[SignalKey.FUEL_USED_CURRENT_LAP] == pytest.approx(0.8)

    # Held again until the next refresh.
    result = drive(lap_count=2, current_lap_time=30_000, gas_level=95.9, dt=1.0)
    assert result[SignalKey.FUEL_USED_CURRENT_LAP] == pytest.approx(0.8)

    # Crossing the line snaps the readout back to zero on that frame.
    result = drive(lap_count=3, current_lap_time=100, gas_level=94.4)
    assert result[SignalKey.FUEL_USED_CURRENT_LAP] == 0.0


def test_live_fuel_rebases_to_zero_after_refuel(drive):
    prime_full_lap(drive, fuel=50.0)
    result = drive(lap_count=2, current_lap_time=30_000, gas_level=48.0, dt=5.0)
    assert result[SignalKey.FUEL_USED_CURRENT_LAP] == pytest.approx(2.0)

    # Pit stop: measured against the rebased level, never negative.
    result = drive(lap_count=2, current_lap_time=60_000, gas_level=95.0)
    assert result[SignalKey.FUEL_USED_CURRENT_LAP] == 0.0


# ---------------------------------------------------------------------------
# Resets
# ---------------------------------------------------------------------------


def test_session_restart_clears_window_and_skips_out_lap(drive):
    prime_full_lap(drive, fuel=97.0)
    drive(lap_count=2, current_lap_time=50_000, gas_level=95.5)
    result = drive(lap_count=3, current_lap_time=100, gas_level=94.4)
    assert result[SignalKey.FUEL_PER_LAP] is not None

    # Restart: lap_count drops, fuel load resets, lap clock resets too.
    result = drive(lap_count=1, current_lap_time=100, gas_level=100.0)
    assert result[SignalKey.FUEL_PER_LAP] is None

    # The first post-restart lap is not banked (rolling starts make it partial).
    drive(lap_count=1, current_lap_time=50_000, gas_level=98.0)
    result = drive(lap_count=2, current_lap_time=100, gas_level=97.0)
    assert result[SignalKey.FUEL_PER_LAP] is None

    # The next full lap banks again.
    drive(lap_count=2, current_lap_time=50_000, gas_level=95.0)
    result = drive(lap_count=3, current_lap_time=100, gas_level=94.4)
    assert result[SignalKey.FUEL_PER_LAP] == pytest.approx(2.6)


def test_track_change_clears_window(drive):
    on_a = {SignalKey.TRACK_ID: "track_a"}
    prime_full_lap(drive, signals=on_a, fuel=97.0)
    drive(on_a, lap_count=2, current_lap_time=50_000, gas_level=95.5)
    result = drive(on_a, lap_count=3, current_lap_time=100, gas_level=94.4)
    assert result[SignalKey.FUEL_PER_LAP] is not None

    result = drive({SignalKey.TRACK_ID: "track_b"}, lap_count=3,
                   current_lap_time=60_000, gas_level=94.0)
    assert result[SignalKey.FUEL_PER_LAP] is None
    assert result[SignalKey.FUEL_LAPS_REMAINING] is None


def test_track_loading_blip_preserves_window(drive):
    on_a = {SignalKey.TRACK_ID: "track_a"}
    prime_full_lap(drive, signals=on_a, fuel=97.0)
    drive(on_a, lap_count=2, current_lap_time=50_000, gas_level=95.5)
    result = drive(on_a, lap_count=3, current_lap_time=100, gas_level=94.4)
    banked = result[SignalKey.FUEL_PER_LAP]
    assert banked is not None

    # track_id drops to None (loading) and comes back as the same circuit.
    drive({SignalKey.TRACK_ID: None}, lap_count=3,
          current_lap_time=10_000, gas_level=94.2)
    result = drive(on_a, lap_count=3, current_lap_time=20_000, gas_level=94.0)
    assert result[SignalKey.FUEL_PER_LAP] == banked


def test_stale_frames_do_not_advance_state(signal, drive):
    drive(lap_count=1, current_lap_time=50_000, gas_level=100.0)
    before = drive(lap_count=1, current_lap_time=60_000, gas_level=99.0,
                   received_time=42.0)

    # Paused: the reader repeats the last frame. Even a frame that looks like
    # a lap boundary must be ignored while received_time does not advance.
    stale = FakeFrame(lap_count=2, current_lap_time=100, gas_level=98.0,
                      received_time=42.0)
    result = signal.update(stale, {}, 0.016)
    assert result == before
    assert signal._lap_valid is False
