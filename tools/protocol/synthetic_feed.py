#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
"""Synthetic Revokyte Telemetry Protocol v1 sender.

Drives a cluster (or a flashed image) with a scripted session — launch
from neutral, an RPM sweep through six gears, delta oscillation, fuel burn,
lap counting — with no game and no console. Pure standard library,
structured like the real feed proxies (argparse + env fallbacks, SIGINT/
SIGTERM handlers, a sendto loop), so it doubles as a reference sender.

The session is a pure function of session time: frame content never depends
on the wall clock or randomness, so ``--record`` produces byte-identical
files on every run (which is how the repository's golden session is
generated and how CI regenerates it to detect drift).

Examples:
    # bench-test a cluster on this machine
    python3 synthetic_feed.py

    # drive a flashed appliance across the LAN at 60 Hz
    python3 synthetic_feed.py --output udp://instrument-cluster.local:5600

    # (re)generate the golden session recording
    python3 synthetic_feed.py --record samples/golden-session.ndjson \\
        --rate 10 --duration 30
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import socket
import sys
import threading
import time
from urllib.parse import urlparse

_DEFAULT_OUTPUT = "udp://127.0.0.1:5600"

# --- session script constants ------------------------------------------------

_LAP_S = 90.0            # scripted lap length
_LAUNCH_S = 2.0          # neutral idle before pulling away
_RAMP_S = 8.0            # seconds to reach the speed profile after launch
_SHIFT_CUT_S = 0.18      # in_gear drops out this long around a gear change
# lower speed bound of each gear (m/s); index 0 = 1st gear
_GEAR_FLOORS = (0.0, 12.0, 22.0, 32.0, 44.0, 58.0)
_TYRE_RADIUS = 0.33      # m
_RPM_IDLE = 900.0
_RPM_MIN, _RPM_MAX = 2800.0, 8800.0
_RPM_WARN = 8300.0
_TAU = 2.0 * math.pi


def parse_udp_url(url: str) -> tuple[str, int]:
    """Parse ``udp://HOST:PORT`` (the ``udp://`` scheme is optional)."""
    if "://" not in url:
        url = "udp://" + url
    parsed = urlparse(url)
    if parsed.scheme.lower() != "udp" or not parsed.hostname or not parsed.port:
        raise ValueError(f"invalid UDP URL {url!r}; expected udp://HOST:PORT")
    return parsed.hostname, int(parsed.port)


# --- the scripted session ----------------------------------------------------

def _speed(t: float) -> float:
    """Speed profile in m/s: still during launch, then a rolling 15–72 m/s
    wave with two peaks per lap, faded in over the ramp."""
    if t < _LAUNCH_S:
        return 0.0
    ramp = min(1.0, (t - _LAUNCH_S) / _RAMP_S)
    wave = 15.0 + 57.0 * 0.5 * (1.0 - math.cos(_TAU * 2.0 * (t - _LAUNCH_S) / _LAP_S))
    return ramp * wave


def _gear(t: float) -> int:
    """−1 while launching (neutral), else the gear the speed profile is in."""
    if t < _LAUNCH_S:
        return -1
    v = _speed(t)
    gear = 1
    for floor in _GEAR_FLOORS[1:]:
        if v >= floor:
            gear += 1
    return gear


def _rpm(t: float) -> float:
    """Sweeps _RPM_MIN.._RPM_MAX across each gear's speed band, so every
    upshift visibly drops the needle."""
    if t < _LAUNCH_S:
        return _RPM_IDLE + 120.0 * math.sin(_TAU * t * 1.5)
    v = _speed(t)
    gear = _gear(t)
    lo = _GEAR_FLOORS[gear - 1]
    hi = _GEAR_FLOORS[gear] if gear < len(_GEAR_FLOORS) else lo + 16.0
    frac = 0.0 if hi <= lo else max(0.0, min(1.0, (v - lo) / (hi - lo)))
    return _RPM_MIN + (_RPM_MAX - _RPM_MIN) * frac


def frame_at(t: float) -> dict:
    """One conformant v1 frame for session time ``t`` (seconds).

    Deterministic: equal ``t`` always yields an identical frame.
    """
    v = _speed(t)
    gear = _gear(t)
    rpm = _rpm(t)
    accelerating = _speed(t + 0.1) >= v
    in_gear = gear > 0 and _gear(t - _SHIFT_CUT_S) == _gear(t + _SHIFT_CUT_S)
    throttle = 0.9 if (accelerating and gear > 0) else 0.05
    brake = 0.0 if accelerating else 0.55
    wheelspin = throttle > 0.8 and rpm > 8000.0

    lap = int(t // _LAP_S)
    lap_frac = (t % _LAP_S) / _LAP_S
    completed = lap  # laps completed so far

    wheels = {}
    for i, corner in enumerate(("front_left", "front_right", "rear_left", "rear_right")):
        rear = corner.startswith("rear")
        slip = 1.04 if (wheelspin and rear) else 1.0
        wheels[corner] = {
            "suspension_height": round(
                max(0.0, min(1.0, 0.5 + 0.35 * math.sin(_TAU * t * 1.3 + i))), 3
            ),
            "radius": _TYRE_RADIUS,
            "rps": round(v * slip / (_TAU * _TYRE_RADIUS), 3),
            "ground_speed": round(v * slip, 3),
            "temperature": round(70.0 + 18.0 * math.sin(_TAU * t / 40.0 + i) + 4.0 * i, 1),
        }

    frame = {
        "v": 1,
        "received_time": round(t, 3),  # diagnostic only; receivers overwrite
        "car_speed": round(v, 3),
        "engine_rpm": round(rpm, 1),
        "current_gear": gear,
        "throttle": round(throttle, 2),
        "brake": round(brake, 2),
        "steering": round(0.35 * math.sin(_TAU * t / 11.0), 3),
        "gas_level": round(max(5.0, 100.0 - 0.05 * t), 2),
        "gas_capacity": 100.0,
        "lap_count": completed + 1,
        "laps_in_race": 10,
        "best_lap_time": 89800 if completed >= 2 else None,
        "last_lap_time": 90000 + (completed % 3) * 350 if completed >= 1 else None,
        "current_lap_time": int((t % _LAP_S) * 1000),
        "native_delta_ms": int(1800 * math.sin(_TAU * t / 13.0)),
        "track_name": "Synthetic Ring",
        "position": {
            "x": round(400.0 * math.sin(_TAU * lap_frac), 2),
            "y": 0.0,
            "z": round(400.0 * math.cos(_TAU * lap_frac), 2),
        },
        "rpm_alert": {"min": _RPM_WARN, "max": _RPM_MAX},
        "flags": {
            "car_on_track": True,
            "in_gear": in_gear,
            "rev_limiter_alert_active": rpm >= _RPM_WARN,
            "tcs_active": wheelspin,
        },
    }
    return frame


# --- entry point -------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synthetic telemetry sender for bench-testing a cluster"
    )
    parser.add_argument("--output",
                        default=os.environ.get("RTP_OUTPUT", _DEFAULT_OUTPUT),
                        help="udp://HOST:PORT sink (or RTP_OUTPUT; default "
                             f"{_DEFAULT_OUTPUT})")
    parser.add_argument("--rate", type=float, default=60.0,
                        help="frames per second (default 60)")
    parser.add_argument("--duration", type=float, default=0.0,
                        help="stop after this many seconds (default: run "
                             "until interrupted; required with --record)")
    parser.add_argument("--record", metavar="PATH",
                        help="write the session as a recording-envelope "
                             "NDJSON file instead of sending UDP")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.rate <= 0:
        sys.stderr.write("--rate must be positive\n")
        return 2

    if args.record:
        if args.duration <= 0:
            sys.stderr.write("--record requires a positive --duration\n")
            return 2
        step = 1.0 / args.rate
        frames = int(args.duration * args.rate)
        with open(args.record, "w", encoding="utf-8") as f:
            for i in range(frames):
                t = round(i * step, 6)
                envelope = {"dt": t, "frame": frame_at(t)}
                f.write(json.dumps(envelope, ensure_ascii=False) + "\n")
        print(f"[synthetic] wrote {frames} frames to {args.record}", flush=True)
        return 0

    host, port = parse_udp_url(args.output)
    print(f"[synthetic] scripted session -> udp://{host}:{port} "
          f"at {args.rate:.0f} Hz", flush=True)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    step = 1.0 / args.rate
    start = time.monotonic()
    sent = 0
    while not stop.is_set():
        t = time.monotonic() - start
        if args.duration > 0 and t >= args.duration:
            break
        line = (json.dumps(frame_at(t), ensure_ascii=False) + "\n").encode("utf-8")
        try:
            sink.sendto(line, (host, port))
        except OSError:
            pass  # transient (e.g. name re-resolution elsewhere); keep pacing
        sent += 1
        if sent == 1 or sent % 1000 == 0:
            print(f"[synthetic] sent {sent} frames", flush=True)
        stop.wait(max(0.0, (start + sent * step) - time.monotonic()))

    sink.close()
    print(f"[synthetic] stopped after {sent} frames", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
