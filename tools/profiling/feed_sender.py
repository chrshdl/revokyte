"""Stand-in feed program: sends NDJSON TelemetryFrames over UDP to the
cluster at a fixed rate, the way the real GT7/ACC feeds do.

Values come from the app's own DemoReader (realistic payload size and
churn), enriched with a synthetic circular driving line + incrementing
lap counter so the real DeltaSignal / TrackSignal compute paths run
(demo mode bypasses them with synthetic signal generators).
"""

import argparse
import json
import math
import socket
import time

from instrument_cluster.telemetry.demo import DemoReader

LAP_SECONDS = 60.0
RADIUS_M = 500.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5600)
    ap.add_argument("--rate", type=float, default=60.0)
    ap.add_argument("--duration", type=float, default=150.0)
    a = ap.parse_args()

    reader = DemoReader()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval = 1.0 / a.rate
    t0 = time.perf_counter()
    next_t = t0
    sent = 0

    while True:
        now = time.perf_counter()
        t = now - t0
        if t >= a.duration:
            break
        if now < next_t:
            time.sleep(min(next_t - now, 0.01))
            continue

        # Strip explicit nulls: TelemetryFrame cannot round-trip its own
        # dump (fields typed `List[float] = None` etc. reject null), and
        # real feeds omit fields they don't have.
        obj = {
            k: v
            for k, v in json.loads(reader.latest().model_dump_json()).items()
            if v is not None
        }
        obj["gear_ratios"] = [3.2, 2.5, 2.0, 1.6, 1.3, 1.1, 0.9, 0.75]
        angle = 2.0 * math.pi * ((t % LAP_SECONDS) / LAP_SECONDS)
        obj["position"] = {
            "x": RADIUS_M * math.sin(angle),
            "y": 0.0,
            "z": RADIUS_M * math.cos(angle),
        }
        obj["lap_count"] = 2 + int(t // LAP_SECONDS)
        obj["current_lap_time"] = int((t % LAP_SECONDS) * 1000)
        obj["car_id"] = 1

        sock.sendto(json.dumps(obj).encode("utf-8"), (a.host, a.port))
        sent += 1
        next_t += interval

    print(f"sent {sent} frames in {t:.1f}s ({sent / t:.1f}/s)")


if __name__ == "__main__":
    main()
