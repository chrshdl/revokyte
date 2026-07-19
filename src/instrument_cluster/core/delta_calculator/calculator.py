"""Per-frame delta orchestration.

:class:`DeltaCalculator` owns the :class:`~delta_calculator.recorder.LapRecorder`
and :class:`~delta_calculator.reference.ReferenceManager`, plus the cross-frame
continuity state. ``process()`` is the single per-frame entry point exported by
the package; everything else here is the projection / continuity / off-track
machinery that turns a raw position into a time delta.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

import numpy as np

from .projection import ProjectionResult, ReferenceTrajectory
from .recorder import LapRecorder
from .reference import ReferenceManager


class DeltaCalculator:
    """
    Calculates time delta vs a reference lap.

    Orchestrates:
     - LapRecorder (telemetry capture),
     - ReferenceManager (trajectory building) and
     - projection / continuity logic.
    """

    def __init__(
        self,
        use_fastest_reference_only: bool = True,
        min_step_m: float = 5.0,
        max_step_m: float = 60.0,
        # continuity / gating
        max_s_jump_m: float = 30.0,
        max_backtrack_m: float = 5.0,
        max_seg_jump: int = 5,
        max_d_perp_m: float = 10.0,
        # reference resampling
        resample_spacing_m: float = 5.0,
        # reference cleanup
        min_seg_len_m: float = 1e-3,
        # reference selection
        min_lap_fraction: float = 0.5,
    ):
        # -- Delegates -------------------------------------------------------
        self._recorder = LapRecorder(min_step_m, max_step_m)
        self._ref_mgr = ReferenceManager(
            resample_spacing_m=resample_spacing_m,
            min_seg_len_m=min_seg_len_m,
            use_fastest_only=use_fastest_reference_only,
            min_lap_fraction=min_lap_fraction,
        )

        # -- Continuity config -----------------------------------------------
        self.max_s_jump_m = float(max_s_jump_m)
        self.max_backtrack_m = float(max_backtrack_m)
        self.max_seg_jump = int(max_seg_jump)
        self.max_d_perp_m = float(max_d_perp_m)

        # -- Session state ---------------------------------------------------
        self._lap_index: int = -1
        self._lap_time_s: float = 0.0
        # Previous frame's GT7 current_lap_time (ms). The master clock resetting
        # (this value dropping) is what marks a new lap — see process().
        self._gt7_prev_ms: Optional[int] = None

        # -- Continuity state ------------------------------------------------
        # Version of the reference trajectory the continuity state refers to.
        # _last_s / _last_seg_idx are arc-length and segment indices on THAT
        # trajectory; when the active reference changes identity (new adoption
        # or a mid-lap use_fastest_reference_only flip) they must be dropped.
        self._active_ref_version: Optional[int] = None
        self._last_s: Optional[float] = None
        self._last_seg_idx: Optional[int] = None
        self._off_track: bool = False
        self._last_was_running: bool = False
        self._last_xz: Optional[tuple] = (
            None  # last (x, z) for off-track dead-reckoning
        )
        self._lap_had_off_track: bool = False  # any off-track excursion this lap?
        self._lap_just_started: bool = False  # first projection of a fresh lap?

        # Why the last lap-change promotion attempt did not adopt a reference
        # (None if it did, or no attempt was made). Surfaced for logging.
        self._last_ref_reject_reason: Optional[str] = None

        # -- Debug -----------------------------------------------------------
        self._dbg_proj: Dict[str, Any] = {}
        self._dbg_state: Dict[str, Any] = {}

    # -- Public API ----------------------------------------------------------

    @property
    def use_fastest_reference_only(self) -> bool:
        return self._ref_mgr.use_fastest_only

    @use_fastest_reference_only.setter
    def use_fastest_reference_only(self, value: bool) -> None:
        self._ref_mgr.use_fastest_only = bool(value)

    @property
    def last_reference_reject_reason(self) -> Optional[str]:
        """Why the most recent lap-change promotion attempt did not adopt a new
        reference, or None if it did (or no attempt was made). Useful for
        logging silent rejections that a ``ref_version`` check can't explain."""
        return self._last_ref_reject_reason

    def reset(self) -> None:
        """Reset session state (e.g. when returning to menu)."""
        self._lap_index = -1
        self._gt7_prev_ms = None
        self._reset_lap()

    def full_reset(self) -> None:
        """Reset everything including the reference trajectory (e.g. track change)."""
        self.reset()
        self._ref_mgr.reset()

    def process(
        self,
        lap_index: int,
        dt: float,
        x: Optional[float],
        y: Optional[float],
        z: Optional[float],
        running: bool,
        gt7_lap_time_ms: Optional[int] = None,
        gt7_last_lap_time_ms: Optional[int] = None,
    ) -> Optional[float]:
        """
        Feed one telemetry frame.

        GT7's current_lap_time (``gt7_lap_time_ms``) is the master lap clock. A
        new lap is defined by that clock *resetting*, not by ``lap_index`` —
        GT7 ticks ``lap_index`` a frame or two before the clock rolls back to
        ~0. Promoting the finished lap to the reference on the clock reset keeps
        the clock and the arc-position aligned across the S/F line; keying it to
        ``lap_index`` instead resets the position to s≈0 while the clock still
        reads the old lap's time, which makes the delta jump by a full lap.

        Returns the time delta (seconds) vs the reference lap, or None
        if no delta can be computed yet.
        """
        # 1. Session reset. lap_index 0/None means we're not in a timed lap.
        if lap_index in (0, None):
            if self._lap_index != -1:
                self.reset()
            return None

        lap_index = int(lap_index)

        if not running:
            self._last_was_running = False
            return None

        # The master clock is required — without it there is no lap time and no
        # delta. (Non-Packet-C sources simply produce no delta.)
        if gt7_lap_time_ms is None or gt7_lap_time_ms < 0:
            self._last_was_running = False
            return None

        # 2. Lap boundary = the master clock resetting. current_lap_time is
        # monotonic within a lap, so a drop below the previous frame's value is
        # the new lap starting: promote the just-finished lap to the reference,
        # then restart per-lap state. The recorder still holds the finished
        # lap's telemetry at this point, so the promotion sees the right data.
        lap_reset = (
            self._gt7_prev_ms is not None and gt7_lap_time_ms < self._gt7_prev_ms
        )
        if lap_reset:
            self._on_lap_change(gt7_last_lap_time_ms=gt7_last_lap_time_ms)
            self._reset_lap()
        self._lap_index = lap_index
        self._gt7_prev_ms = gt7_lap_time_ms

        # Detect resume after pause/teleport: force full KDTree re-latch so the
        # constrained window doesn't start from the pre-teleport segment.
        if not self._last_was_running:
            self._last_seg_idx = None
            self._last_s = None
        self._last_was_running = True

        # 3. Advance the lap clock straight from GT7's master timer.
        self._lap_time_s = gt7_lap_time_ms / 1000.0

        # 4. Record telemetry & calculate delta
        if x is not None and z is not None:
            vx, vy, vz = float(x), float(y or 0.0), float(z)
            self._recorder.record(vx, vy, vz, self._lap_time_s)

            if self._ref_mgr.has_reference:
                return self._calculate_delta(vx, vy, vz)

        return None

    def get_debug_state(self) -> Optional[dict]:
        traj = self._ref_mgr.trajectory
        if traj is None:
            return None

        pts = traj.seg_p0
        last_pt = pts[-1] + traj.seg_vec[-1]
        all_pts = np.vstack((pts, last_pt))

        return {
            "ref_version": traj.version,
            "ref_lap_time": float(traj.times[-1]),
            "ref_reject_reason": self._last_ref_reject_reason,
            "ref_xs": all_pts[:, 0],
            "ref_ys": all_pts[:, 1],
            "ref_zs": all_pts[:, 2],
            "proj": dict(self._dbg_proj),
            "state": dict(self._dbg_state),
        }

    # -- Internals -----------------------------------------------------------

    def _on_lap_change(self, gt7_last_lap_time_ms: Optional[int] = None) -> None:
        """Promote the just-finished lap to a reference (or record why not).

        Called when ``lap_index`` ticks. The previous lap's recorder still holds
        its telemetry; this is the one chance to adopt it before ``_reset_lap``
        clears it.
        """
        if self._lap_index <= 0:
            return

        # Prefer GT7's authoritative last_lap_time over _lap_time_s. The calc
        # clock can end up short when stale frames near the S/F line freeze
        # _lap_time_s for the last fraction of a second while GT7's timer
        # keeps running to the crossing. An artificially-low lap_time would
        # also make the fastest-lap gate unreachable for any real follow-up lap.
        if gt7_last_lap_time_ms is not None and gt7_last_lap_time_ms > 0:
            lap_time = gt7_last_lap_time_ms / 1000.0
        else:
            lap_time = self._lap_time_s

        if self._lap_had_off_track:
            # Don't promote a lap with an off-track excursion. A dirty lap has
            # extra time baked into its time-vs-distance curve; adopting it
            # offsets every following lap's delta by roughly the time spent
            # off-track. The live delta still updates during the excursion
            # (dead-reckoning in _calculate_delta), so this only governs which
            # lap becomes the stored reference — like track-limits invalidation
            # on a pro timer.
            self._last_ref_reject_reason = "off-track excursion (dirty time curve)"
        elif self._ref_mgr.try_update(self._recorder, lap_time):
            self._last_ref_reject_reason = None
        else:
            self._last_ref_reject_reason = self._ref_mgr.last_reject_reason

    def _reset_lap(self) -> None:
        """Reset per-lap state (recorder, continuity, debug)."""
        self._lap_time_s = 0.0
        self._recorder.reset()
        self._last_s = None
        self._last_seg_idx = None
        self._off_track = False
        self._last_was_running = False
        self._last_xz = None
        self._lap_had_off_track = False
        self._lap_just_started = True
        self._dbg_proj = {}
        self._dbg_state = {}

    def _set_dbg_state(
        self,
        traj: ReferenceTrajectory,
        proj: ProjectionResult,
        *,
        last_s: Optional[float],
        s_raw: float,
        s_final: float,
        ds: float,
        t_ref: float,
        delta: Optional[float],
        off_track: bool,
    ) -> None:
        """Record per-frame debug state (mirrored over UDP to the tuning tool).

        Centralised so the three exit paths of ``_calculate_delta`` (off-track
        dead-reckon, off-track no-latch, on-track) can't drift apart.
        """
        self._dbg_state = {
            "ref_version": traj.version,
            "lap_len": traj.lap_length,
            "lap_time": self._lap_time_s,
            "last_s": last_s,
            "s_raw": s_raw,
            "s_final": s_final,
            "ds": ds,
            "d_perp": proj.dist_h,
            "d_3d": proj.dist_3d,
            "seg_idx": proj.seg_idx,
            "t_ref": t_ref,
            "delta": delta,
            "off_track": off_track,
        }

    def _set_dbg_proj(
        self, qx: float, qy: float, qz: float, proj: ProjectionResult
    ) -> None:
        """Record the raw projection geometry for this frame (debug only)."""
        self._dbg_proj = {
            "qx": qx,
            "qy": qy,
            "qz": qz,
            "s_raw": proj.s,
            "d_h": proj.dist_h,
            "d_3d": proj.dist_3d,
            "seg_idx": proj.seg_idx,
            "fx": float(proj.point_on_line[0]),
            "fy": float(proj.point_on_line[1]),
            "fz": float(proj.point_on_line[2]),
            "p0x": float(proj.segment_origin[0]),
            "p0y": float(proj.segment_origin[1]),
            "p0z": float(proj.segment_origin[2]),
            "p1x": float(proj.segment_end[0]),
            "p1y": float(proj.segment_end[1]),
            "p1z": float(proj.segment_end[2]),
            "t": proj.t_seg,
        }

    def _calculate_delta(self, qx: float, qy: float, qz: float) -> Optional[float]:
        traj = self._ref_mgr.trajectory
        if traj is None:
            return None

        # The active reference can change identity mid-lap (the previous-lap /
        # fastest-lap selection flipping, or a fresh adoption). The continuity
        # state indexes the OLD trajectory's arc-length and segments, so
        # clamping against it on the new one would drag the delta through
        # garbage — drop it and let the full KDTree search re-latch, the same
        # treatment as a teleport.
        if traj.version != self._active_ref_version:
            self._active_ref_version = traj.version
            self._last_s = None
            self._last_seg_idx = None

        q_point = np.array([qx, qy, qz])

        # 1. Project — constrained if we have continuity AND are on-track.
        # Off-track frames use the full KDTree so we re-latch to the correct
        # position when the car returns (e.g. after a chicane excursion or
        # teleport landing).
        if self._last_seg_idx is not None and not self._off_track:
            proj = traj.project_constrained(
                q_point,
                self._last_seg_idx,
                self.max_seg_jump,
            )
        else:
            proj = traj.project(q_point)

        if proj is None:
            return None

        self._set_dbg_proj(qx, qy, qz, proj)

        # 2. Off-track handling.
        if proj.dist_h > self.max_d_perp_m:
            return self._delta_off_track(traj, proj, qx, qz)

        # 3. On track (or just got back) — project with continuity clamping.
        return self._delta_on_track(traj, proj, qx, qz)

    def _delta_off_track(
        self,
        traj: ReferenceTrajectory,
        proj: ProjectionResult,
        qx: float,
        qz: float,
    ) -> Optional[float]:
        """Off-track frame: the nearest-segment projection is unreliable (it may
        latch onto a topologically wrong segment, e.g. between two legs of a
        chicane). Rather than blank the delta — which freezes the display and is
        not how pro predictive timers behave — we dead-reckon the arc-position
        forward by the distance the car actually travelled this frame (the
        MoTeC-style "distance odometer keeps integrating" model) and keep
        emitting a delta. The first on-track frame re-latches to the KDTree
        projection (the ``was_off_track`` branch in ``_delta_on_track``). The
        lap is also marked dirty so it is not promoted to the reference.
        """
        self._off_track = True
        self._lap_had_off_track = True
        # This counts as the lap's first projection: the S/F seam snap in
        # _delta_on_track must not fire on a later on-track re-latch (which
        # would yank a car that's genuinely deep into the lap back to s=0).
        self._lap_just_started = False

        if self._last_s is not None and self._last_xz is not None:
            step = math.hypot(qx - self._last_xz[0], qz - self._last_xz[1])
            step = min(step, self.max_s_jump_m)  # guard against teleports
            s_dead = max(0.0, min(self._last_s + step, traj.lap_length))
            self._last_s = s_dead
            self._last_xz = (qx, qz)

            t_ref = traj.get_time_at_s(s_dead)
            delta = float(self._lap_time_s - t_ref)
            self._set_dbg_state(
                traj,
                proj,
                last_s=self._last_s,
                s_raw=proj.s,
                s_final=s_dead,
                ds=step,
                t_ref=t_ref,
                delta=delta,
                off_track=True,
            )
            return delta

        # No latched position yet (off-track before the first valid projection
        # of the lap) — we cannot estimate progress, so blank this frame only.
        self._last_xz = (qx, qz)
        self._set_dbg_state(
            traj,
            proj,
            last_s=self._last_s,
            s_raw=proj.s,
            s_final=self._last_s or 0.0,
            ds=0.0,
            t_ref=(
                traj.get_time_at_s(self._last_s) if self._last_s is not None else 0.0
            ),
            delta=None,
            off_track=True,
        )
        return None

    def _delta_on_track(
        self,
        traj: ReferenceTrajectory,
        proj: ProjectionResult,
        qx: float,
        qz: float,
    ) -> float:
        """On-track frame: apply continuity clamping and return the time delta."""
        was_off_track = self._off_track
        self._off_track = False

        # Continuity logic (clamp jumps).
        # Skip clamping on the first frame of a lap, after a teleport re-latch
        # (last_s is None), or on the re-latch frame after an off-track excursion
        # so we jump directly to the correct position instead of catching up
        # 30 m at a time.
        lap_len = traj.lap_length
        s_raw = max(0.0, min(float(proj.s), lap_len))
        last_s = self._last_s
        s_final = s_raw

        if last_s is None or was_off_track:
            # Jump straight to the KDTree projection with no clamp when there is
            # no prior position (fresh lap / running=False gap) or on the first
            # on-track frame after an off-track excursion — otherwise we'd crawl
            # back to the true position max_s_jump_m at a time. On a fresh lap,
            # resolve the S/F seam ambiguity on closed loops: the car sits on the
            # S/F line and the projection can land on either s≈0 or s≈lap_len, so
            # a far-half match on a fresh lap is the wrap-around — snap to start.
            if (
                last_s is None
                and self._lap_just_started
                and traj.closed
                and s_final > 0.5 * lap_len
            ):
                s_final = 0.0
        else:
            ds = s_final - float(last_s)
            # The arc-position must not wrap into a new lap on its own: under the
            # clock-as-master model the sole lap boundary is the master clock
            # resetting (which triggers _reset_lap and a fresh, seam-snapped
            # projection). A raw step near a full lap is the car crossing S/F a
            # frame or two before the clock resets; clamp it so s is held near
            # the lap end rather than jumping back to ~0 while the clock still
            # reads the finishing lap's time (which would spike the delta by a
            # full lap). The clock reset then re-latches s to ~0.
            if ds > self.max_s_jump_m:
                ds = self.max_s_jump_m
            elif ds < -self.max_backtrack_m:
                ds = -self.max_backtrack_m

            s_final = float(last_s) + ds

        s_final = max(0.0, min(s_final, lap_len))

        # First on-track fix of the lap is committed — the seam snap above only
        # applies to that frame.
        self._lap_just_started = False

        # Update continuity state.
        # On an off-track re-latch proj.seg_idx came from an unconstrained
        # KDTree search that can match a geometrically-close but topologically-
        # wrong segment (e.g. a hairpin leg that runs parallel to the current
        # one). Derive the segment index from the clamped s_final instead, so
        # the next constrained search starts from the correct neighbourhood.
        self._last_s = s_final
        if was_off_track and last_s is not None:
            n_segs = len(traj.seg_p0)
            seg = int(np.searchsorted(traj.seg_s0, s_final, side="right")) - 1
            self._last_seg_idx = max(0, min(seg, n_segs - 1))
        else:
            self._last_seg_idx = proj.seg_idx
        self._last_xz = (qx, qz)

        # Time delta
        t_ref = traj.get_time_at_s(s_final)
        delta = float(self._lap_time_s - t_ref)

        self._set_dbg_state(
            traj,
            proj,
            last_s=last_s,
            s_raw=s_raw,
            s_final=s_final,
            ds=0.0 if last_s is None else (s_final - last_s),
            t_ref=t_ref,
            delta=delta,
            off_track=False,
        )

        return delta
