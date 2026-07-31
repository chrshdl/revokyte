from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class Flags(BaseModel):
    car_on_track: bool = False
    paused: bool = False
    loading_or_processing: bool = False
    in_gear: bool = False  # 0 when shifting or out of gear, standing
    has_turbo: bool = False
    rev_limiter_alert_active: bool = False
    hand_brake_active: bool = False
    lights_active: bool = False
    lights_high_beams_active: bool = False
    lights_low_beams_active: bool = False
    asm_active: bool = False
    tcs_active: bool = False


class Vector(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Wheels(BaseModel):
    front_left: Wheel
    front_right: Wheel
    rear_left: Wheel
    rear_right: Wheel


class Wheel(BaseModel):
    suspension_height: float = Field(ge=0, le=1)
    radius: float  # in meters
    rps: float  # rotations per second (not radians like default)
    ground_speed: float  # meters per second
    temperature: float = 20.0


class Bounds(BaseModel):
    min: float = Field(
        default=7500.0,
        description="Indicates RPM rev warning.",
    )
    max: float = Field(
        default=8000.0,
        description="Indicates RPM when rev limiter is hit.",
    )


class TelemetryFrame(BaseModel):
    # Monotonic timestamp of when this frame was *received*, stamped by the
    # reader (UdpJsonlReader / the direct readers) — feeds do not need to
    # set it. It is the freshness clock: a value that stops changing is how
    # DeltaSignal, FuelSignal and LinkSignal all detect a dead or paused
    # link, so it must come from the receiving side to be trustworthy.
    received_time: float = 0.0
    car_id: int = -1
    car_speed: float = 0.0
    engine_rpm: float = 0.0
    current_gear: int = 0  # 0 is reverse, -1 is neutral
    # Pedal positions, 0.0 (released) .. 1.0 (fully applied). GT7 transmits
    # raw 0-255 bytes; the readers normalize. A feed that emits raw bytes
    # anyway is caught by ThrottleNormalizer (telemetry/units.py) on the
    # consumer side.
    throttle: float = 0.0
    brake: float = 0.0
    steering: float = 0.0
    gas_level: float = 0.0  # remaining fuel; ~0-100 for most cars, 0 for EVs
    gas_capacity: float = 0.0  # 100 normal cars, 5 karts, 0 EVs
    lap_count: int | None = None
    laps_in_race: int | None = None
    best_lap_time: int | None = None
    last_lap_time: int | None = None
    current_lap_time: int | None = None  # ms; Packet C only
    flags: Flags = None
    rpm_alert: Bounds = Field(
        default=None,
        description="rpm alerts",
    )
    wheels: Wheels = None
    position: Vector | None = None
    gear_ratios: List[float] = None
    # Optional values a source may already have computed upstream. When set,
    # the delta/track signals republish them instead of computing (see their
    # native short-circuits). GT7's feed leaves both None; a feed that provides
    # its own delta / track name (e.g. ACC's Broadcasting API) sets them.
    native_delta_ms: int | None = None
    track_name: str | None = None
