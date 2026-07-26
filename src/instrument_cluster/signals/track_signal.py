import json
import math
from pathlib import Path
from typing import Dict, List, Tuple

from ..telemetry.models import TelemetryFrame
from ..ui.widgets.track_name_widget import TrackNameWidget
from .signal_keys import SignalKey

# Bundled, read-only database shipped inside the package. Sourced from the
# GT7 telemetry community rather than recorded on-device: each entry's
# start/finish gate and bounding box come from Bornhall/gt7telemetry's
# gt7trackdetect.csv, joined against ddm999/gt7info's course.csv for names.
# GT7 exposes no track/course ID in telemetry, so this is the same trick
# tools like GT7toMoTeC and sim-to-motec use to identify the circuit.
_BUNDLED_DB = Path(__file__).resolve().parent.parent / "db" / "tracks.json"

# Published as the track name until a track is identified. The identifier
# never publishes a provisional guess: the first name shown is final (a
# wrong-then-corrected readout is worse than a short "---").
_NO_TRACK_TEXT = TrackNameWidget._DEFAULT_TRACK_TEXT

# The car "crosses a gate" when its frame-to-frame path segment intersects
# the gate segment — an exact test, not a radius. Two circuits can sit 10 m
# apart in GT7's per-venue coordinate space (Interlagos's line is ~9 m from
# Sardegna Road's), so proximity alone misidentifies where an intersection
# test cannot.
#
# The gate endpoints come from one contributor's crossing, so the recorded
# line can be slightly narrower than the real start/finish line. Pad both
# ends so an edge-hugging crossing still intersects.
_GATE_END_PAD_M = 5.0

# Ignore path segments longer than this (teleports: reset-to-track, replay
# scrubbing, packet-loss gaps). 50 m/frame is 10,800 km/h at 60 fps; even
# half a second of dropped packets at 300 km/h stays under it.
_TELEPORT_M = 50.0

# Cheap bounding-box rejection before the exact segment test, so the
# per-frame scan over 100+ tracks stays fast.
_PREFILTER_MARGIN_M = 60.0

# GT7's lap_count increments exactly at the physical start/finish line
# (delta_signal.py relies on the same fact: the lap clock resets a frame or
# two after lap_count ticks). A gate crossing therefore only identifies the
# track when it coincides with a lap tick — that is the game itself
# confirming "this line, not some other layout's line we merely drive
# across" (e.g. the Nordschleife-layout and Tourist-layout gates both lie on
# every Nurburgring-24h lap). Tick and crossing land within a frame or two
# of each other; allow a generous pairing window.
_TICK_PAIR_WINDOW_FRAMES = 15

# Sibling layouts that share a start/finish gate and crossing direction
# (Brands Hatch GP/Indy, Suzuka/Suzuka East, Nurburgring 24h/GP, ...) are
# indistinguishable at the line, so identification is deferred and the lap
# is watched instead. A candidate is eliminated once the car drives further
# than this outside its bounding box — generous enough to absorb kerb-hopping
# and wide lines, far smaller than the hundreds of metres by which sibling
# layouts differ (the tightest pair in the DB, Blue Moon's infields A/B,
# differ by ~50 m).
_ESCAPE_MARGIN_M = 40.0

# When a full line-to-line lap has been observed, the lap's own bounding box
# is fitted against each surviving candidate's stored box (max deviation of
# the four edges) and the best fit wins. If even the best fit is worse than
# this, something is off (corrupted window, off-map excursion) — keep
# waiting rather than lock a bad guess.
_FIT_SANITY_M = 200.0

# Motion with essentially no x-component can't produce the "PX"/"NX"
# crossing direction the gate convention encodes; skip such (anomalous)
# frames rather than guess between a forward/reverse gate pair.
_MIN_DX_M = 1e-6


def _bounds_contains(bounds: dict, x: float, z: float, margin: float = 0.0) -> bool:
    return (
        bounds["min_x"] - margin <= x <= bounds["max_x"] + margin
        and bounds["min_z"] - margin <= z <= bounds["max_z"] + margin
    )


def _bounds_area(bounds: dict) -> float:
    return (bounds["max_x"] - bounds["min_x"]) * (bounds["max_z"] - bounds["min_z"])


def _bounds_fit_error(bounds: dict, obs: List[float]) -> float:
    """Max deviation between a candidate's bounding box and the observed
    lap's box (obs = [min_x, max_x, min_z, max_z]). A lap driven on the
    candidate scores near zero; a lap driven on a nested sibling misses the
    parent's far edges by hundreds of metres."""
    return max(
        abs(bounds["min_x"] - obs[0]),
        abs(bounds["max_x"] - obs[1]),
        abs(bounds["min_z"] - obs[2]),
        abs(bounds["max_z"] - obs[3]),
    )


def _segments_cross(
    px: float,
    pz: float,
    qx: float,
    qz: float,
    ax: float,
    az: float,
    bx: float,
    bz: float,
) -> bool:
    """True if segment p→q (the car's path this frame) intersects segment
    a→b (a gate). Collinear overlap counts as no crossing: a real crossing
    is transversal — the car passes through the line, not along it."""
    d1x, d1z = qx - px, qz - pz
    d2x, d2z = bx - ax, bz - az
    denom = d1x * d2z - d1z * d2x
    if abs(denom) < 1e-12:
        return False
    t = ((ax - px) * d2z - (az - pz) * d2x) / denom
    u = ((ax - px) * d1z - (az - pz) * d1x) / denom
    return 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0


class TrackSignal:
    """Identifies the current circuit from position telemetry.

    Publication contract: the name shown is never revised. Until the
    evidence singles out one track, the placeholder is published; once a
    name is published it only changes through a track/replay load.

    Identification pipeline, per frame while unlocked:

    1. Detect start/finish-line crossings exactly (path-segment against
       gate-segment intersection, direction-matched).
    2. Anchor a crossing with GT7's lap counter: only a crossing that
       coincides with a lap_count tick is the true line (layouts sharing
       tarmac drive across each other's lines mid-lap without a tick).
       If lap data is unavailable, crossings anchor on their own.
    3. A uniquely-anchored gate locks immediately. Gate-sharing siblings
       stay pending — publish nothing, watch the lap: eliminate candidates
       whose bounding box the car escapes (identifies the larger sibling
       mid-lap), and after a full line-to-line lap fit the observed lap's
       bounding box against the survivors (identifies the smallest sibling
       at the next crossing).

    Known limit: layout pairs whose extent is identical in the database —
    chicane variants (Monza / No Chicane, Fuji / Short, Le Mans, Spa / 24h,
    Barcelona GP / No Chicane) and Daytona Tri-Oval vs Road Course (the
    infield never moves the box) — cannot be separated by any position
    evidence this database can express. The best-fitting sibling is locked
    deterministically.
    """

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or _BUNDLED_DB
        self._db: Dict = self._load_tracks()

        # Per-direction gate table derived from the static DB, with the
        # prefilter margin folded into the bounds and the end pad into the
        # gate segment. _gates_crossed runs every unlocked frame over every
        # track; scanning flat tuples instead of nested dicts is what keeps
        # that affordable at 60 Hz.
        self._gate_table = self._build_gate_table()

        # The active track, identified from the gate database. Once set we
        # hold the lock until a track/replay load clears it, so the readout
        # doesn't flicker.
        self._current_track_id: str | None = None
        self._locked: bool = False

        # Previous frame's position: source of the path segment used for
        # crossing detection.
        self._prev_x: float | None = None
        self._prev_z: float | None = None

        # Lap bookkeeping. _prev_lap persists across pending resets; a
        # decrease means a session restart and clears identification state.
        self._prev_lap: int | None = None
        self._frame_no: int = 0

        # Gate-sharing sibling group awaiting resolution (None = no pending
        # hypothesis). While set, the placeholder is published.
        self._pending: List[str] | None = None

        # Observed-position bounding box [min_x, max_x, min_z, max_z] since
        # the last lap tick; _obs_full marks that the window started at the
        # start/finish line (an anchored tick), i.e. that by the next tick it
        # spans one complete lap and is valid evidence for the box fit.
        self._obs: List[float] | None = None
        self._obs_full: bool = False

        # Tick/crossing pairing state: recent crossings (frame_no, ids) and
        # an unpaired tick's (frame_no, obs-snapshot) awaiting its crossing.
        self._recent_crossings: List[Tuple[int, List[str]]] = []
        self._pending_tick: Tuple[int, Tuple[List[float] | None, bool]] | None = (
            None
        )

    def _load_tracks(self) -> Dict:
        if not self.db_path.exists():
            return {}
        try:
            with open(self.db_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def stop(self) -> None:
        """No-op: the track database is bundled and read-only, nothing to flush."""

    def update(self, frame: TelemetryFrame, signals: dict) -> dict:
        # Native short-circuit: if the source already knows the track name,
        # publish it directly and skip the GT7 gate/bounds geometry (which
        # assumes GT7's per-venue coordinate space). Keyed on the data, never on
        # the game — a feed that names its own track (e.g. ACC) sets track_name;
        # GT7's feed leaves it None and falls through to identification below.
        native_name = getattr(frame, "track_name", None) if frame is not None else None
        if native_name:
            return {SignalKey.TRACK_ID: native_name, SignalKey.TRACK_NAME: native_name}

        # A track/replay load clears the active track so a restarted drive is
        # re-identified from scratch and laps on a newly loaded circuit are
        # not attributed to the previous one.
        flags = getattr(frame, "flags", None) if frame is not None else None
        if flags is not None and flags.loading_or_processing:
            self._reset_identification()
            self._prev_lap = None
            self._current_track_id = None
            self._locked = False

        # Hold an existing lock: nothing below may revise it.
        if self._locked and self._current_track_id in self._db:
            return self._publish_current()

        pos = getattr(frame, "position", None) if frame is not None else None
        if pos is None or (pos.x == 0.0 and pos.z == 0.0):
            self._prev_x = self._prev_z = None
            return {SignalKey.TRACK_ID: None, SignalKey.TRACK_NAME: _NO_TRACK_TEXT}
        x, z = pos.x, pos.z

        self._frame_no += 1

        lap = getattr(frame, "lap_count", None)
        if not isinstance(lap, int):
            lap = None
        tick = False
        if lap is not None:
            if self._prev_lap is not None:
                if lap > self._prev_lap:
                    tick = True
                elif lap < self._prev_lap:
                    # Session restart (retry, new event): stale evidence.
                    self._reset_identification()
            self._prev_lap = lap

        on_track = bool(flags.car_on_track) if flags is not None else True

        # --- 1. exact crossing detection on this frame's path segment ---
        crossed: List[str] = []
        if self._prev_x is not None:
            dx, dz = x - self._prev_x, z - self._prev_z
            if 0.0 < math.hypot(dx, dz) <= _TELEPORT_M:
                crossed = self._gates_crossed(self._prev_x, self._prev_z, x, z, dx)
        self._prev_x, self._prev_z = x, z
        if crossed:
            self._recent_crossings.append((self._frame_no, crossed))
        self._recent_crossings = [
            (f, ids)
            for f, ids in self._recent_crossings
            if self._frame_no - f <= _TICK_PAIR_WINDOW_FRAMES
        ]

        # Grow the observed-lap box. Excursion frames (car off track after a
        # spin) are excluded so a trip through a gravel trap can't distort
        # the evidence against the true layout.
        if on_track:
            self._grow_obs(x, z)

        # --- 2. anchor crossings with the lap counter ---
        anchor: List[str] | None = None
        anchor_obs: Tuple[List[float] | None, bool] = (None, False)
        if lap is None:
            # No lap data in this mode: a crossing must anchor on its own.
            if crossed:
                anchor = crossed
                anchor_obs = (list(self._obs) if self._obs else None, self._obs_full)
        else:
            if tick:
                snapshot = (list(self._obs) if self._obs else None, self._obs_full)
                # Pair with the most recent crossing event only: the true
                # line is the one essentially simultaneous with the tick.
                # (Coincident sibling gates share one event; an unrelated
                # gate crossed a few frames earlier must not pollute it.)
                recent: List[str] = (
                    self._recent_crossings[-1][1] if self._recent_crossings else []
                )
                if recent:
                    anchor = recent
                    anchor_obs = snapshot
                    self._obs_full = True  # new window starts on the line
                else:
                    # Tick without a crossing nearby (yet): either the pairing
                    # crossing arrives within the window (see below), or this
                    # tick wasn't at a known gate (race-start tick on the
                    # grid, unknown track) and the window stays provisional.
                    self._pending_tick = (self._frame_no, snapshot)
                    self._obs_full = False
                self._obs = [x, x, z, z]
                self._recent_crossings = []
            elif crossed and self._pending_tick is not None:
                tick_frame, snapshot = self._pending_tick
                if self._frame_no - tick_frame <= _TICK_PAIR_WINDOW_FRAMES:
                    anchor = crossed
                    anchor_obs = snapshot
                    self._pending_tick = None
                    self._obs_full = True  # window effectively began at the line
            if (
                self._pending_tick is not None
                and self._frame_no - self._pending_tick[0] > _TICK_PAIR_WINDOW_FRAMES
            ):
                self._pending_tick = None

        # --- 3. resolve / defer ---
        if anchor:
            resolved = self._resolve(anchor, anchor_obs)
            if lap is None and crossed:
                # Without lap data the anchored crossing itself starts the
                # line-to-line observation window.
                self._obs = [x, x, z, z]
                self._obs_full = True
            if resolved is not None:
                self._set_lock(resolved)
                return self._publish_current()
        elif self._pending is not None and on_track:
            self._prune_pending(x, z)
            if self._locked:
                return self._publish_current()

        return {SignalKey.TRACK_ID: None, SignalKey.TRACK_NAME: _NO_TRACK_TEXT}

    # --- identification internals ---

    def _resolve(
        self,
        anchor: List[str],
        anchor_obs: Tuple[List[float] | None, bool],
    ) -> str | None:
        """Turn an anchored line crossing into a lock, a pending hypothesis,
        or nothing (a foreign layout's line). Returns the track id to lock."""
        if self._pending is not None:
            pool = [t_id for t_id in self._pending if t_id in anchor]
            if not pool:
                # Not our hypothesis's line (e.g. crossing the Nordschleife
                # layout's gate mid-24h-lap, in the odd case it also ticked).
                return None
        else:
            pool = list(anchor)

        if len(pool) == 1:
            return pool[0]

        obs, obs_full = anchor_obs
        if obs_full and obs is not None:
            best = min(
                pool,
                key=lambda t_id: (
                    _bounds_fit_error(self._db[t_id]["bounds"], obs),
                    _bounds_area(self._db[t_id]["bounds"]),
                ),
            )
            if _bounds_fit_error(self._db[best]["bounds"], obs) <= _FIT_SANITY_M:
                return best

        # Can't separate the siblings yet: hold the hypothesis, publish
        # nothing, and let the lap decide (escape pruning below, or the box
        # fit at the next anchored crossing).
        self._pending = pool
        return None

    def _prune_pending(self, x: float, z: float) -> None:
        """Eliminate pending candidates whose bounding box the car has
        escaped; a single survivor locks mid-lap (how the larger of two
        nested siblings is identified without waiting for the full lap)."""
        assert self._pending is not None
        remaining = [
            t_id
            for t_id in self._pending
            if _bounds_contains(self._db[t_id]["bounds"], x, z, margin=_ESCAPE_MARGIN_M)
        ]
        if not remaining:
            # Escaped every candidate at once (off-map blip): keep waiting.
            return
        if len(remaining) == 1:
            self._set_lock(remaining[0])
        else:
            self._pending = remaining

    def _build_gate_table(self) -> Dict[str, list]:
        """Flatten the DB into per-direction tuples of
        (min_x, max_x, min_z, max_z, ax, az, bx, bz, track_id) —
        margin-expanded bounds and end-padded gate endpoints."""
        table: Dict[str, list] = {"PX": [], "NX": []}
        m = _PREFILTER_MARGIN_M
        for t_id, data in self._db.items():
            gate = data.get("gate")
            bounds = data.get("bounds")
            if gate is None or bounds is None:
                continue  # malformed entry — never auto-matched
            entries = table.get(gate.get("direction"))
            if entries is None:
                continue
            p1, p2 = gate["p1"], gate["p2"]
            ax, az, bx, bz = p1["x"], p1["z"], p2["x"], p2["z"]
            length = math.hypot(bx - ax, bz - az)
            if length > 0.0:
                ux, uz = (bx - ax) / length, (bz - az) / length
                ax, az = ax - ux * _GATE_END_PAD_M, az - uz * _GATE_END_PAD_M
                bx, bz = bx + ux * _GATE_END_PAD_M, bz + uz * _GATE_END_PAD_M
            entries.append(
                (
                    bounds["min_x"] - m,
                    bounds["max_x"] + m,
                    bounds["min_z"] - m,
                    bounds["max_z"] + m,
                    ax,
                    az,
                    bx,
                    bz,
                    t_id,
                )
            )
        return table

    def _gates_crossed(
        self, px: float, pz: float, x: float, z: float, dx: float
    ) -> List[str]:
        """All tracks whose start/finish gate the path segment (p → current)
        crosses in the gate's recorded direction."""
        if abs(dx) < _MIN_DX_M:
            return []
        out: List[str] = []
        for min_x, max_x, min_z, max_z, ax, az, bx, bz, t_id in self._gate_table[
            "PX" if dx > 0 else "NX"
        ]:
            if not (
                (min_x <= px <= max_x and min_z <= pz <= max_z)
                or (min_x <= x <= max_x and min_z <= z <= max_z)
            ):
                continue
            if _segments_cross(px, pz, x, z, ax, az, bx, bz):
                out.append(t_id)
        return out

    def _grow_obs(self, x: float, z: float) -> None:
        if self._obs is None:
            self._obs = [x, x, z, z]
            return
        o = self._obs
        if x < o[0]:
            o[0] = x
        elif x > o[1]:
            o[1] = x
        if z < o[2]:
            o[2] = z
        elif z > o[3]:
            o[3] = z

    def _set_lock(self, t_id: str) -> None:
        self._current_track_id = t_id
        self._locked = True
        self._reset_identification()

    def _reset_identification(self) -> None:
        """Drop all in-flight evidence (pending siblings, observation window,
        tick pairing). Does not touch the lock or lap bookkeeping."""
        self._pending = None
        self._obs = None
        self._obs_full = False
        self._recent_crossings = []
        self._pending_tick = None
        self._prev_x = self._prev_z = None

    def _publish_current(self) -> dict:
        return {
            SignalKey.TRACK_ID: self._current_track_id,
            SignalKey.TRACK_NAME: self._db[self._current_track_id]["name"],
        }
