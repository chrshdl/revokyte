# Track database & diagnostics

This directory holds the data the dashboard uses to identify which GT7
circuit is being driven, plus tooling to inspect that data when the
identification misbehaves.

| File | What it is |
|---|---|
| `tracks.json` | The bundled, read-only track database (~100 layouts). GPL-3.0, see `NOTICE.md`. |
| `NOTICE.md` | Provenance and licensing of `tracks.json` (derived from GPL-3.0 data). |
| `plot_diagnostics.py` | Diagnostic plots + ambiguity analysis of `tracks.json` (this guide). |
| `plot_tracks.py` | Older, minimal overlap plot (all boxes + gates in one interactive matplotlib window). |
| `overview.png`, `brands_hatch.png` | Outputs of `plot_diagnostics.py` in static mode. |

## The data model

GT7's telemetry contains **no track or course ID**, so identification works
purely from car position. Each `tracks.json` entry describes one layout:

```json
"119": {
  "name": "Brands Hatch Grand Prix Circuit",
  "gate": {
    "p1": { "x": -145.8, "z": -410.8 },
    "p2": { "x": -138.8, "z": -395.8 },
    "direction": "PX"
  },
  "bounds": { "min_x": -417.1, "max_x": 415.3, "min_z": -464.3, "max_z": 468.9 }
}
```

- **`gate`** — the start/finish line as a segment in the x/z plane.
  `direction` is the sign of the car's x-movement when crossing it
  legitimately: `PX` = crossing while moving toward +x, `NX` = toward −x.
  Forward/reverse layout pairs share a gate location but differ here.
- **`bounds`** — the axis-aligned bounding box of the layout's driven area.
- The key (`"119"`) is GT7's community-known course ID.

Provenance: gates and bounds come from
[Bornhall/gt7telemetry](https://github.com/Bornhall/gt7telemetry)'s
`gt7trackdetect.csv` (GPL-3.0), joined against
[ddm999/gt7info](https://github.com/ddm999/gt7info)'s `course.csv` (MIT-0)
for display names. Because of its GPL-licensed origin, `tracks.json` itself
is distributed under **GPL-3.0** — see [`NOTICE.md`](NOTICE.md) — while the
application code stays MIT. The file is bundled and read-only at runtime; a
track missing from it is simply never identified — the dashboard keeps
showing the `---` placeholder.

Coordinates are **per-venue local**: every circuit is centred near its own
origin, so bounding boxes of unrelated venues overlap heavily in this
space. Only the gates are distinctive — that is the core fact the
identifier (and these plots) are built around.

## plot_diagnostics.py

### Setup

`matplotlib` ships with the dev dependency group:

```bash
uv venv && source .venv/bin/activate && uv sync
```

### Static mode (default)

```bash
uv run python src/instrument_cluster/db/plot_diagnostics.py
```

Writes into this directory:

- **`overview.png`** — every bounding box (gray, dashed-thin) and every
  start/finish gate (dark marks), equal aspect. Shows at a glance that
  boxes are useless for telling venues apart while gates are small and
  well separated.
- **`brands_hatch.png`** — the canonical ambiguity: Brands Hatch GP (119)
  and Indy (346) share one gate, crossed in the same direction, with
  Indy's box nested inside GP's. Every "gate-sharing siblings" case in the
  database has this shape.

And prints to the terminal:

- the Brands Hatch pair's raw numbers (gate, direction, box, area);
- **gate-sharing groups**: every cluster of tracks whose gate midpoints
  lie within 25 m of each other, with each entry's crossing direction,
  e.g.

  ```
  Suzuka Circuit [PX] | Suzuka Circuit East Course [PX]
  Alsace - Village [PX] | Alsace - Village Reverse [NX]
  ```

  Within a group, members with **different** directions (`PX` vs `NX`)
  are separated by the crossing direction alone. Members with the **same**
  direction are true siblings — indistinguishable at the line — and are
  exactly the cases `TrackSignal` must resolve by watching the lap.

### Interactive mode

```bash
uv run python src/instrument_cluster/db/plot_diagnostics.py --interactive   # or -i
```

Opens both figures as live windows (requires a GUI session — on the Pi or
over plain SSH use static mode instead). Controls:

| Action | Effect |
|---|---|
| **Hover** over a gate or box edge | Tooltip with `id · name` of everything under the cursor. Gate hits are listed first; bounding-box edges are suffixed `(box edge)`. Coincident gates list all their siblings — hovering the Brands Hatch gate shows both 119 and 346. |
| **Scroll wheel** | Zoom in/out, centred on the cursor (aspect stays 1:1). |
| **`r`** | Reset to the initial view. |
| Toolbar | Standard matplotlib pan / rectangle-zoom / home / save. |

Note on hovering while fully zoomed out: the hit radius is a few screen
points, which at full extent corresponds to tens of metres of data space,
so several `(box edge)` entries may ride along. Zoom in and the tooltip
gets specific.

### Typical workflow: investigating a misclassification

1. Run the script and find the offending track in the printed
   **gate-sharing groups**.
2. Not in any group → its gate is unique; a wrong identification means the
   gate/bounds data itself is off (compare against a telemetry capture).
3. In a group with **opposite directions** → the crossing direction should
   have separated it; suspect the `direction` field or the telemetry path.
4. In a group with the **same direction** → it's a true sibling pair.
   Zoom into it interactively and compare the bounding boxes:
   - **Nested / offset boxes** (GP vs Indy, Suzuka vs East, 24h vs GP,
     Blue Moon infields…): resolvable — `TrackSignal` defers publication
     and decides from where the lap actually goes (box escape, then a
     full-lap box fit).
   - **Near-identical boxes**: geometrically unresolvable from this data.
     All six such pairs, with the max box-edge deviation (every one is far
     below the 40 m escape margin; the next-tightest pair in the database,
     Blue Moon Bay's infields A/B, sits at ~43–50 m and is resolvable):
     - Circuit de Spa-Francorchamps (462) / Spa 24h Layout (1269) — 3.5 m
     - 24 Heures du Mans Racing Circuit (454) / No Chicane (854) — 3.7 m
     - Daytona Tri-Oval (4) / Daytona Road Course (1163) — 3.7 m (the
       infield doesn't move the box)
     - Fuji International Speedway (16) / Short (837) — 5.3 m
     - Autodromo Nazionale Monza (469) / No Chicane (742) — 12.1 m
     - Circuit de Barcelona-Catalunya Grand Prix Layout (874) / No
       Chicane (1249) — 14.3 m

     For these the identifier locks the best-fitting sibling
     deterministically.

## How `TrackSignal` uses this data

For the full picture read `../signals/track_signal.py` (heavily
commented) and the *Signal Processors* section of the repo's `CLAUDE.md`.
In one paragraph: the identifier detects an exact path-over-gate crossing
in the recorded direction, requires it to coincide with a `lap_count` tick
(GT7 increments the counter exactly at the true line, which rejects
mid-lap crossings of other layouts' lines — a Nürburgring 24h lap drives
across the Nordschleife and Tourist layouts' gates), and for gate-sharing
siblings publishes nothing until box-escape or a full-lap box fit singles
one out. The published name is never revised; until then the dashboard
shows `---`.
