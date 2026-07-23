---
description: Profile the cluster on the Pi with the SIGTERM-safe cProfile harness (UDP/pydantic/UI)
argument-hint: [live|synthetic|demo|idle] [duration-seconds]
---

Profile the instrument cluster on the Pi using the harness in `tools/profiling/`. The live service must be stopped while the harness runs (only one process can hold the DRM master), and **must be restarted afterwards even if a step fails**.

Arguments: `$ARGUMENTS`

- First argument is the scenario, default `live`:
  - **live** — profile against the real game feed during a race. Uses the device's real config (`IC_CONFIG_PATH=/data/config/instrument-cluster.json`); the user must already have the cluster in UDP mode with the game feed installed and the game running. Do not start `feed_sender.py`.
  - **synthetic** — no game needed: start `feed_sender.py` on the Pi first (60 Hz NDJSON with synthetic laps/position so the real DeltaSignal/TrackSignal paths run), and use the scratch config `/data/profiling/config-udp.json`.
  - **demo** — demo mode, scratch config `/data/profiling/config-demo.json`.
  - **idle** — UDP mode with no feed (scratch config, no sender).
- Second argument is the profile duration in seconds, default `120`. The harness self-terminates via SIGTERM after this long, so a run never needs to be killed by hand (and `systemctl stop`/Ctrl-C also produce a valid profile).

**Always pass `--udp-inline` for UDP scenarios** (live/synthetic/idle). Python 3.12's cProfile also captures threads spawned after `enable()` and the concurrent updates corrupt the profile (verified on-device); `--udp-inline` drains the UDP socket on the main loop instead of the reader thread so packet decode + pydantic validation appear in the profile with correct attribution.

Steps (address is `root@instrument-cluster.local`, never a numeric IP; if ssh refuses after a re-flash run `ssh-keygen -R instrument-cluster.local`):

1. Push the current scripts and make sure the scratch configs exist:

   ```bash
   ssh root@instrument-cluster.local "mkdir -p /data/profiling"
   scp tools/profiling/*.py root@instrument-cluster.local:/data/profiling/
   ssh root@instrument-cluster.local "cd /data/profiling && python3 -c \"
   import json
   cfg = json.load(open('/data/config/instrument-cluster.json'))
   cfg['telemetry_mode'] = 'demo'; json.dump(cfg, open('config-demo.json','w'), indent=4)
   cfg['telemetry_mode'] = 'udp';  json.dump(cfg, open('config-udp.json','w'), indent=4)\""
   ```

2. Run the scenario in ONE ssh invocation so the service restart cannot be skipped (example: `live`, 120 s; adjust `IC_CONFIG_PATH`, `--udp-inline`, and the sender per scenario above — for `synthetic` start the sender before the harness with `nohup python3 /data/profiling/feed_sender.py --duration <duration+30> >/data/profiling/feed_sender.log 2>&1 &` and `pkill -f feed_sender` after):

   ```bash
   ssh root@instrument-cluster.local '
   systemctl stop instrument-cluster
   env SDL_VIDEODRIVER=kmsdrm MESA_LOADER_DRIVER_OVERRIDE=v3d PYOPENGL_PLATFORM=egl \
       PYTHONDONTWRITEBYTECODE=1 IC_CONFIG_PATH=/data/config/instrument-cluster.json \
       python3 /data/profiling/harness.py --out /data/profiling/live-$(date +%Y%m%d-%H%M).prof \
       --duration 120 --udp-inline 2>&1 | tail -1
   python3 /data/profiling/pydantic_bench.py
   systemctl start instrument-cluster
   sleep 3
   systemctl is-active instrument-cluster
   '
   ```

   The pydantic bench needs no display and takes ~30 s; it measures per-packet feed deserialization (`json.loads` + `model_validate`) which runs on the reader thread in production and is therefore invisible to the main profile.

3. Pull the `.prof` into a temp dir and analyze locally:

   ```bash
   d=$(mktemp -d) && scp root@instrument-cluster.local:"/data/profiling/*.prof" "$d/"
   python3 tools/profiling/analyze.py summary "$d"/<name>.prof
   python3 tools/profiling/analyze.py top "$d"/<name>.prof
   ```

4. Report: achieved fps (`frames / total`), the wait/GL/app bucket split, the top app-code entries by tottime, and the pydantic µs/packet numbers. Baseline for comparison (2026-07-24, Pi 5, demo): ~60.7 fps, flip 45% / clock-tick 34% (both idle waits — leave alone), glTexSubImage2D upload ~8.5% (~1.6 ms/frame), app code ~4.7%.

Notes:
- `systemctl stop` mid-run is safe: the harness converts SIGTERM into a clean exit and still writes the profile.
- Everything lands in `/data/profiling/` (the writable partition); the rootfs is never touched, so this works through the normal RAUC/hawkBit deployment with no image changes.
- During a live race the cluster is dark for the profile duration — warn the user before stopping the service.
