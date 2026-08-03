"""FuelFlowObserver: model-rate integration and the k scale observer.

A stub service with a constant-rate fuel map makes every expectation
computable by hand: at FLOW_G_S grams/s and the k prior, the observer's
unit outputs are exact products.
"""

from dataclasses import dataclass, field

import pytest

from instrument_cluster.signals.fuel_flow import (
    FuelFlowObserver,
    _K0_UNITS_PER_G,
    _K_CLAMP,
)
from instrument_cluster.signals.fuel_signal import FuelSignal
from instrument_cluster.signals.signal_keys import SignalKey

FLOW_G_S = 5.0


class StubMap:
    def fuel_flow(self, rpm, throttle):
        return FLOW_G_S


class StubService:
    """Maps exist for every non-negative car id, immediately."""

    def __init__(self):
        self.requested = []

    def request(self, car_id):
        self.requested.append(car_id)

    def poll(self, car_id):
        if car_id is not None and car_id >= 0:
            return StubMap()
        return None


@dataclass
class FakeFlags:
    paused: bool = False
    loading_or_processing: bool = False
    car_on_track: bool = True


@dataclass
class FakeFrame:
    car_id: int = 42
    engine_rpm: float = 5000.0
    throttle: float = 0.8
    gas_level: float = 100.0
    gas_capacity: float = 100.0
    lap_count: int | None = 1
    current_lap_time: int | None = 1000
    received_time: float = 0.0
    flags: FakeFlags = field(default_factory=FakeFlags)


@pytest.fixture
def observer():
    return FuelFlowObserver(service=StubService())


# --- activation guards ---


def test_inert_until_throttle_moves(observer):
    frame = FakeFrame(throttle=0.0)
    observer.update(frame, 0.016)
    assert not observer.active
    assert observer.rate_units_s() is None
    assert observer.units_since_anchor() == 0.0

    observer.update(FakeFrame(throttle=0.5), 0.016)
    assert observer.active
    assert observer.rate_units_s() == pytest.approx(FLOW_G_S * _K0_UNITS_PER_G)


def test_inert_without_a_map(observer):
    observer.update(FakeFrame(car_id=-1, throttle=1.0), 0.016)
    assert not observer.active
    assert observer.rate_units_s() is None


def test_car_change_requests_map_and_resets(observer):
    observer.update(FakeFrame(car_id=42, throttle=1.0), 1.0)
    assert observer._service.requested == [42]
    assert observer.units_since_anchor() > 0.0

    observer.update(FakeFrame(car_id=99, throttle=0.0), 0.016)
    assert observer._service.requested == [42, 99]
    assert observer.units_since_anchor() == 0.0
    assert not observer.active  # throttle liveness re-proven per car


# --- integration and anchoring ---


def test_integral_accumulates_and_rebases(observer):
    frame = FakeFrame(throttle=1.0)
    for _ in range(10):
        observer.update(frame, 0.1)  # 1 s total -> FLOW_G_S grams
    assert observer.units_since_anchor() == pytest.approx(
        FLOW_G_S * _K0_UNITS_PER_G, rel=1e-6
    )
    observer.rebase_anchor()
    assert observer.units_since_anchor() == 0.0


# --- k scale observer ---


def test_k_converges_toward_measured_scale(observer):
    """Feed measured drops that imply twice the prior scale; the EMA must
    walk k upward, clamped inside the sane window."""
    gas = 100.0
    frame = FakeFrame(throttle=1.0, gas_level=gas)
    observer.update(frame, 0.016)  # opens the observation window

    k_before = observer._k
    for _ in range(30):
        # 10 s of model burn = 50 g; report a drop of 50 g * 2*k0 units
        for _ in range(10):
            observer.update(FakeFrame(throttle=1.0, gas_level=gas), 1.0)
        gas -= 50.0 * (2.0 * _K0_UNITS_PER_G)
        observer.update(FakeFrame(throttle=1.0, gas_level=gas), 0.016)

    assert observer._k > k_before
    assert observer._k <= _K_CLAMP[1]
    assert observer._k == pytest.approx(2.0 * _K0_UNITS_PER_G, rel=0.1)


def test_gas_rise_discards_observation_window(observer):
    observer.update(FakeFrame(throttle=1.0, gas_level=50.0), 1.0)
    k_before = observer._k
    # refuel: level jumps up — the pending window must not feed the EMA
    observer.update(FakeFrame(throttle=1.0, gas_level=99.0), 1.0)
    observer.update(FakeFrame(throttle=1.0, gas_level=98.5), 1.0)
    assert observer._k == k_before


def test_tiny_drops_are_ignored_as_quantization(observer):
    observer.update(FakeFrame(throttle=1.0, gas_level=50.0), 1.0)
    k_before = observer._k
    observer.update(FakeFrame(throttle=1.0, gas_level=49.95), 1.0)
    assert observer._k == k_before


# --- FuelSignal composition ---


def _drive(signal, t, **kwargs):
    dt = kwargs.pop("dt", 0.016)
    kwargs.setdefault("received_time", t)
    return signal.update(FakeFrame(**kwargs), {}, dt)


def test_fuel_signal_publishes_rate_and_smooth_live_used():
    signal = FuelSignal(flow_observer=FuelFlowObserver(service=StubService()))

    # Arm lap tracking (partial lap, then the line crossing).
    out = _drive(signal, 1.0, lap_count=1, current_lap_time=50_000, throttle=1.0)
    out = _drive(signal, 2.0, lap_count=2, current_lap_time=100, throttle=1.0)
    assert out[SignalKey.FUEL_USED_CURRENT_LAP] == pytest.approx(0.0, abs=1e-9)

    # Between measured refreshes the readout climbs with the model even
    # though gas_level has not moved.
    out = _drive(signal, 3.0, lap_count=2, current_lap_time=200, throttle=1.0,
                 dt=1.0)
    assert out[SignalKey.FUEL_USED_CURRENT_LAP] > 0.0
    assert out[SignalKey.FUEL_RATE] == pytest.approx(
        FLOW_G_S * signal._flow._k
    )


def test_fuel_signal_outputs_unchanged_when_observer_inert():
    class DeadService(StubService):
        def poll(self, car_id):
            return None

    signal = FuelSignal(flow_observer=FuelFlowObserver(service=DeadService()))
    _drive(signal, 1.0, lap_count=1, current_lap_time=50_000, throttle=1.0)
    out = _drive(signal, 2.0, lap_count=2, current_lap_time=100, throttle=1.0)
    assert out[SignalKey.FUEL_RATE] is None
    assert out[SignalKey.FUEL_USED_CURRENT_LAP] == pytest.approx(0.0)
    # sample-and-hold semantics preserved: no model climb between refreshes
    out = _drive(signal, 3.0, lap_count=2, current_lap_time=200, dt=1.0)
    assert out[SignalKey.FUEL_USED_CURRENT_LAP] == pytest.approx(0.0)
