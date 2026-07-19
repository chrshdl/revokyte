from dataclasses import dataclass


@dataclass(frozen=True)
class SignalMeta:
    type: type
    unit: str
    producer: str


class SignalKey:
    """String constants for all known VehicleBus signal keys."""

    DELTA_DIFF = "delta_diff"
    DELTA_DIFF_STABLE = "delta_diff_stable"
    DELTA_REF_LAP_TIME = "delta_ref_lap_time"
    DELTA_REFERENCE_MODE = "delta_reference_mode"
    FUEL_PER_LAP = "fuel_per_lap"
    FUEL_USED_CURRENT_LAP = "fuel_used_current_lap"
    FUEL_LAPS_REMAINING = "fuel_laps_remaining"
    TRACK_ID = "track_id"
    TRACK_NAME = "track_name"


SIGNAL_REGISTRY: dict[str, SignalMeta] = {
    SignalKey.DELTA_DIFF: SignalMeta(float, "s", "DeltaSignal"),
    SignalKey.DELTA_DIFF_STABLE: SignalMeta(float, "s", "DeltaSignal"),
    SignalKey.DELTA_REF_LAP_TIME: SignalMeta(float, "s", "DeltaSignal"),
    SignalKey.DELTA_REFERENCE_MODE: SignalMeta(str, "", "DeltaSignal"),
    SignalKey.FUEL_PER_LAP: SignalMeta(float, "", "FuelSignal"),
    SignalKey.FUEL_USED_CURRENT_LAP: SignalMeta(float, "", "FuelSignal"),
    SignalKey.FUEL_LAPS_REMAINING: SignalMeta(float, "", "FuelSignal"),
    SignalKey.TRACK_ID: SignalMeta(str, "", "TrackSignal"),
    SignalKey.TRACK_NAME: SignalMeta(str, "", "TrackSignal"),
}
