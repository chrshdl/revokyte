"""
Utility for wrapping noisy signals with sample-and-hold hysteresis
to prevent display flickering in UI widgets.
"""
import math


class StableSignal:
    """
    Wraps a raw signal value with sample-and-hold hysteresis.

    Motorsport-style display update limiting:
    - Updates display only every `refresh_period` seconds
    - Applies hysteresis threshold to filter small fluctuations
    - Holds last displayed value between refresh instants
    """

    def __init__(
        self,
        refresh_period: float = 0.2,
        hysteresis: float = 0.02,
    ):
        """
        Args:
            refresh_period: How often to allow display updates (seconds).
            hysteresis: Minimum change required to trigger an update.
        """
        self._refresh_period = refresh_period
        self._hysteresis = hysteresis

        self._displayed_value: float | None = None
        self._refresh_timer: float = 0.0
        self._force_refresh: bool = True

    @property
    def value(self) -> float | None:
        """The current stabilized value to display."""
        return self._displayed_value

    def update(self, raw_value: float | None, dt: float) -> float | None:
        """
        Process a new raw sample and return the stabilized display value.

        Args:
            raw_value: The latest raw signal value (can be None or NaN).
            dt: Time delta since last update (seconds).

        Returns:
            The stabilized value to display (may be same as previous).
        """
        # invalid sample: hold current value
        if raw_value is None or not math.isfinite(raw_value):
            return self._displayed_value

        # first valid sample or forced refresh: update immediately
        if self._displayed_value is None or self._force_refresh:
            self._displayed_value = raw_value
            self._refresh_timer = 0.0
            self._force_refresh = False
            return self._displayed_value

        # accumulate time
        self._refresh_timer += max(0.0, dt)

        # at refresh instant, apply hysteresis
        if self._refresh_timer >= self._refresh_period:
            assert self._displayed_value is not None  # guaranteed by check above
            if abs(raw_value - self._displayed_value) >= self._hysteresis:
                self._displayed_value = raw_value

            # wrap timer for next period
            if self._refresh_period > 0.0:
                self._refresh_timer %= self._refresh_period
            else:
                self._refresh_timer = 0.0

        return self._displayed_value

    def reset(self) -> None:
        """Reset internal state, forcing immediate update on next sample."""
        self._displayed_value = None
        self._refresh_timer = 0.0
        self._force_refresh = True

    def force_refresh(self) -> None:
        """Force an immediate update on the next valid sample."""
        self._force_refresh = True
        self._refresh_timer = 0.0
