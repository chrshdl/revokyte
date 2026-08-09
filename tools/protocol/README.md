# Protocol conformance kit

Tooling for the [Revokyte Telemetry Protocol v1](../../docs/PROTOCOL.md).
Everything here is **pure Python standard library** and runs anywhere a feed
runs — no dependencies, no install.

Unlike the rest of this repository (GPL-3.0), the files in this directory are
licensed **MIT-0** ([`LICENSES/MIT-0.txt`](../../LICENSES/MIT-0.txt)) and the
sample data is **CC0-1.0**, so third-party sender implementations — including
proprietary ones — can copy from them freely. See PROTOCOL.md §9.

## `validate.py` — conformance validator

```bash
# validate wire frames or recordings (auto-detected per line)
python3 validate.py samples/full.ndjson mycapture.ndjson
```

Validates NDJSON files against
[`docs/telemetry-frame.v1.schema.json`](../../docs/telemetry-frame.v1.schema.json):
either raw wire frames (one JSON object per line) or recording-envelope files
(`{"dt": …, "frame": …}`, PROTOCOL.md Appendix A — `dt` monotonicity is checked
too). Exit 0 = all frames valid. It interprets only the schema subset the v1
schema uses; `tests/protocol/` cross-checks its verdicts against the reference
`jsonschema` package.

## `synthetic_feed.py` — scripted session sender

Bench-test a cluster or a freshly flashed image with no game and no console:

```bash
python3 synthetic_feed.py                                        # localhost
python3 synthetic_feed.py --output udp://instrument-cluster.local:5600
python3 synthetic_feed.py --rate 10                              # slow-tier sender
```

The session is scripted and deterministic: neutral launch, an RPM sweep
through six gears (with visible shift drops and `in_gear` cuts), delta
oscillation, fuel burn, lap counting on a 90 s synthetic lap. It doubles as a
minimal reference sender: argparse + env config, SIGINT/SIGTERM handling and a
paced `sendto` loop, exactly like the real feed proxies.

## `samples/` — golden data (CC0-1.0)

| File | Contents |
|---|---|
| `minimal.ndjson` | The smallest useful frame (speed + RPM only). |
| `full.ndjson` | Every defined channel populated. |
| `optional-absent.ndjson` | Legal omissions: empty frame, nullable fields as null, `gas_capacity: 0` (no fuel model), neutral/reverse gears, paused frame. |
| `invalid/*.ndjson` | Frames a receiver rejects, one rule per file: null on omit-never-null fields, null gear, byte-range pedals, unclamped suspension, wrong types, wrong `v`. |
| `golden-session.ndjson` | 30 s scripted session, 10 Hz, recording-envelope format. Regenerate byte-identically with `python3 synthetic_feed.py --record samples/golden-session.ndjson --rate 10 --duration 30` (CI asserts this). |
