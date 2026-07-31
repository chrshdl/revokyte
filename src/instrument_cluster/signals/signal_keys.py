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
    DELTA_STATE = "delta_state"
    FUEL_PER_LAP = "fuel_per_lap"
    FUEL_USED_CURRENT_LAP = "fuel_used_current_lap"
    FUEL_LAPS_REMAINING = "fuel_laps_remaining"
    FUEL_RATE = "fuel_rate"
    TRACK_ID = "track_id"
    TRACK_NAME = "track_name"
    TELEMETRY_STALE = "telemetry_stale"
    TELEMETRY_AGE_S = "telemetry_age_s"


class DeltaState:
    """Why the delta gauge has no number to show.

    ``None`` (the absence of a state) means armed: a reference lap exists
    and the numeric delta is the thing to display. The tokens below are the
    GT3-dash vocabulary the gauge falls back to, each naming a *different*
    cause — a driver who sees NO_REF has lost a reference they had, which
    is not the same situation as never having had one (REF_LAP).
    """

    BEACON = "beacon"    # not in a timed lap — waiting for the S/F beacon
    REF_LAP = "ref_lap"  # timed lap running, recording the first reference
    NO_REF = "no_ref"    # an established reference was discarded


SIGNAL_REGISTRY: dict[str, SignalMeta] = {
    SignalKey.DELTA_DIFF: SignalMeta(float, "s", "DeltaSignal"),
    SignalKey.DELTA_DIFF_STABLE: SignalMeta(float, "s", "DeltaSignal"),
    SignalKey.DELTA_REF_LAP_TIME: SignalMeta(float, "s", "DeltaSignal"),
    SignalKey.DELTA_REFERENCE_MODE: SignalMeta(str, "", "DeltaSignal"),
    SignalKey.DELTA_STATE: SignalMeta(str, "", "DeltaSignal"),
    SignalKey.FUEL_PER_LAP: SignalMeta(float, "", "FuelSignal"),
    SignalKey.FUEL_USED_CURRENT_LAP: SignalMeta(float, "", "FuelSignal"),
    SignalKey.FUEL_LAPS_REMAINING: SignalMeta(float, "", "FuelSignal"),
    SignalKey.FUEL_RATE: SignalMeta(float, "units/s", "FuelSignal"),
    SignalKey.TRACK_ID: SignalMeta(str, "", "TrackSignal"),
    SignalKey.TRACK_NAME: SignalMeta(str, "", "TrackSignal"),
    SignalKey.TELEMETRY_STALE: SignalMeta(bool, "", "LinkSignal"),
    SignalKey.TELEMETRY_AGE_S: SignalMeta(float, "s", "LinkSignal"),
}
