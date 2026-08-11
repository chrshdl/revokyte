"""Static demo values so the editor's canvas shows live-looking views.

No network, no threads, no scan paths — just plausible numbers for the
gauges and fixed fake lists for the Wi-Fi and EnterIP screens.
"""

from __future__ import annotations

from instrument_cluster.telemetry.models import (
    Flags,
    TelemetryFrame,
    Vector,
    Wheel,
    Wheels,
)


def demo_frame() -> TelemetryFrame:
    return TelemetryFrame(
        received_time=1.0,
        car_id=1,
        car_speed=61.9,  # m/s ≈ 223 km/h
        engine_rpm=5200.0,
        current_gear=4,
        throttle=0.8,
        gas_level=12.4,
        gas_capacity=100.0,
        lap_count=2,
        best_lap_time=97_980,
        last_lap_time=98_450,
        current_lap_time=45_120,
        flags=Flags(car_on_track=True, in_gear=True),
        wheels=Wheels(
            front_left=_wheel(87.0),
            front_right=_wheel(87.0),
            rear_left=_wheel(85.0),
            rear_right=_wheel(85.0),
        ),
        position=Vector(x=0.0, y=0.0, z=0.0),
    )


def _wheel(temp: float) -> Wheel:
    return Wheel(
        suspension_height=0.1,
        radius=0.33,
        rps=30.0,
        ground_speed=61.9,
        temperature=temp,
    )


#: (ssid, secured, signal_dbm) — a spread of bars, one current network.
FAKE_NETWORKS = [
    ("Home Network", True, -48),
    ("Garage 5G", True, -60),
    ("Paddock Guest", False, -72),
    ("Neighbours", True, -80),
    ("Track WiFi", False, -85),
    ("Cafe Hotspot", True, -88),
]

FAKE_CURRENT_SSID = "Home Network"

FAKE_RECENT_IPS = ["192.168.1.10", "192.168.1.22", "10.0.0.5"]

FAKE_SIGNALS = {
    "delta_diff_stable": 0.19,
    "delta_diff": 0.19,
    "track_name": "Circuit de la Sarthe",
}
