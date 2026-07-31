"""FuelFlowObserver: physics-based fuel rate between measured anchors.

GT7's ``gas_level`` is quantized and lap-anchored; the engine model's
fuel map is continuous but in grams of a *model* engine. This observer
integrates the map's g/s at the live (rpm, throttle) and learns a scale
factor k (game units per gram) from measured gas_level drops, so the
game's own fuel logic stays ground truth and the model only fills in
the space between its samples.

Inert until a map exists and throttle has actually moved — an ACC
session (throttle never mapped) or a missing artifact leaves every
output None and FuelSignal behaving exactly as before.
"""

from __future__ import annotations

from ..core.engine_sim.service import get_service
from ..telemetry.models import TelemetryFrame
from ..telemetry.units import ThrottleNormalizer

# Scale prior: a ~100-unit tank over a ~45 kg fill.
_K0_UNITS_PER_G = 100.0 / 45_000.0
_K_CLAMP = (0.25 * _K0_UNITS_PER_G, 4.0 * _K0_UNITS_PER_G)
_K_EMA_ALPHA = 0.15
# A measured drop smaller than this is quantization noise, not a sample.
_MIN_MEASURED_DROP = 0.2
_MIN_MODEL_GRAMS = 1.0
# The observer only trusts itself once the pedal has provably moved.
_THROTTLE_LIVE_MIN = 0.05


class FuelFlowObserver:
    def __init__(self, service=None):
        self._service = service if service is not None else get_service()
        self._normalizer = ThrottleNormalizer()

        self._car_id: int | None = None
        self._k = _K0_UNITS_PER_G
        self._throttle_seen = False
        self._rate_g_s = 0.0

        self._grams_anchor = 0.0  # integral value at the last rebase
        self._grams_total = 0.0
        # k-observer bookkeeping between measured drops
        self._obs_gas: float | None = None
        self._obs_grams = 0.0

    # -- FuelSignal-facing API --

    def update(self, frame: TelemetryFrame, dt: float) -> None:
        """Advance the integral one live frame. The caller has already
        gated on frame freshness (received_time) and EVs."""
        if frame.car_id != self._car_id:
            self._car_id = frame.car_id
            self._service.request(frame.car_id)
            self._normalizer.reset()
            self._reset_integration()

        fuel_map = self._service.poll(frame.car_id)
        if fuel_map is None:
            self._rate_g_s = 0.0
            return

        throttle = self._normalizer(frame.throttle)
        if throttle > _THROTTLE_LIVE_MIN:
            self._throttle_seen = True
        if not self._throttle_seen:
            return

        self._rate_g_s = fuel_map.fuel_flow(frame.engine_rpm, throttle)
        self._grams_total += self._rate_g_s * dt
        self._observe(frame.gas_level)

    def rate_units_s(self) -> float | None:
        """Instantaneous burn in game units/s; None while inert."""
        if not self.active:
            return None
        return self._rate_g_s * self._k

    def units_since_anchor(self) -> float:
        return (self._grams_total - self._grams_anchor) * self._k

    def rebase_anchor(self) -> None:
        """Snap the integral to a fresh measured value; called whenever
        FuelSignal (re)samples gas_level as truth."""
        self._grams_anchor = self._grams_total

    def freeze_observation(self) -> None:
        """Discard the running k-observation window — a refuel, restart
        or link loss makes the pending gas_level delta meaningless."""
        self._obs_gas = None

    @property
    def active(self) -> bool:
        return (
            self._throttle_seen
            and self._service.poll(self._car_id) is not None
        )

    # -- internals --

    def _reset_integration(self) -> None:
        self._throttle_seen = False
        self._rate_g_s = 0.0
        self._grams_total = 0.0
        self._grams_anchor = 0.0
        self._obs_gas = None
        self._obs_grams = 0.0

    def _observe(self, gas_level: float) -> None:
        if self._obs_gas is None:
            self._obs_gas = gas_level
            self._obs_grams = self._grams_total
            return
        drop = self._obs_gas - gas_level
        if drop < _MIN_MEASURED_DROP:
            if drop < 0.0:
                # gas rose: refuel slipped through — restart the window
                self.freeze_observation()
            return
        grams = self._grams_total - self._obs_grams
        if grams >= _MIN_MODEL_GRAMS:
            sample = drop / grams
            k = (1.0 - _K_EMA_ALPHA) * self._k + _K_EMA_ALPHA * sample
            self._k = min(max(k, _K_CLAMP[0]), _K_CLAMP[1])
        self._obs_gas = gas_level
        self._obs_grams = self._grams_total
