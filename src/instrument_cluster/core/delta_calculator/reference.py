"""Reference-lap construction and reference selection.

Turns a recorder's raw point stream into an immutable
:class:`~delta_calculator.projection.ReferenceTrajectory`: arc-length, short
segment cleanup, uniform resampling, and the gating that decides whether a
completed lap is allowed to become (or replace) a reference.

Two references are kept side by side — the most recent clean lap and the
fastest plausible lap of the session — so the selection mode
(``use_fastest_only``) can flip mid-lap and the active reference swaps
instantly instead of waiting for the next adoption.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import numpy as np

from .projection import ReferenceTrajectory

if TYPE_CHECKING:
    from .recorder import LapRecorder


class ReferenceManager:
    """
    Builds *ReferenceTrajectory* objects from recorded lap data.

    Maintains two reference slots on every clean lap regardless of the
    selection mode — the most recent lap and the fastest plausible lap of the
    session — and exposes the one selected by ``use_fastest_only``. Flipping
    the mode mid-session therefore swaps the active reference immediately,
    and switching back to fastest-only can never end up gating candidates
    against a best time whose trajectory was overwritten during a
    previous-lap stint.
    """

    def __init__(
        self,
        resample_spacing_m: float,
        min_seg_len_m: float,
        use_fastest_only: bool = False,
        min_lap_fraction: float = 0.5,
    ):
        self._resample_spacing_m = float(resample_spacing_m)
        self._min_seg_len_m = float(min_seg_len_m)

        self._use_fastest_only = use_fastest_only
        self._min_lap_fraction = float(min_lap_fraction)
        self._last_traj: Optional[ReferenceTrajectory] = None
        self._best_traj: Optional[ReferenceTrajectory] = None
        # Always paired with _best_traj: set together, cleared together.
        self._best_lap_time_s: Optional[float] = None
        # Monotonic id handed to each built trajectory. Deliberately survives
        # reset() so a version compare detects every identity change of the
        # active reference — across adoptions, mode flips and full resets.
        self._next_version: int = 0
        # Why the most recent try_update() did not adopt a reference (None if it
        # did). Lets the caller log/surface gated rejections that otherwise look
        # identical to "nothing happened".
        self._last_reject_reason: Optional[str] = None

    # -- public API ----------------------------------------------------------

    @property
    def trajectory(self) -> Optional[ReferenceTrajectory]:
        """The active reference, selected by ``use_fastest_only``."""
        return self._best_traj if self._use_fastest_only else self._last_traj

    @property
    def has_reference(self) -> bool:
        return self.trajectory is not None

    @property
    def last_reject_reason(self) -> Optional[str]:
        """Reason the last try_update() rejected the candidate, or None if it
        was adopted."""
        return self._last_reject_reason

    def reset(self) -> None:
        """Clear both reference trajectories and the best lap time."""
        self._last_traj = None
        self._best_traj = None
        self._best_lap_time_s = None
        self._last_reject_reason = None

    @property
    def use_fastest_only(self) -> bool:
        return self._use_fastest_only

    @use_fastest_only.setter
    def use_fastest_only(self, value: bool) -> None:
        self._use_fastest_only = bool(value)

    def try_update(self, recorder: "LapRecorder", lap_time: float) -> bool:
        """
        Try to build a new reference trajectory from the recorder's data.

        A lap with valid geometry always refreshes the previous-lap slot and,
        when it beats the plausibility-gated session best, the fastest slot
        too — independent of the current mode, so a later mode flip has both
        references ready. Returns True if the *active* reference (selected by
        ``use_fastest_only``) changed, False otherwise (not enough data, or
        the lap wasn't faster in fastest-only mode). On rejection the reason
        is available via the ``last_reject_reason`` property.
        """
        if not recorder.has_data:
            self._last_reject_reason = "insufficient telemetry (need ≥2 recorded points)"
            return False

        xs = np.asarray(recorder.xs, dtype=np.float32)
        ys = np.asarray(recorder.ys, dtype=np.float32)
        zs = np.asarray(recorder.zs, dtype=np.float32)
        ts = np.asarray(recorder.times, dtype=np.float32)

        # -- Arc-length from raw recorded points ----------------------------
        dx = np.diff(xs)
        dy = np.diff(ys)
        dz = np.diff(zs)
        seg_len = np.sqrt(dx * dx + dy * dy + dz * dz)
        s_raw = np.concatenate(([0.0], np.cumsum(seg_len))).astype(np.float32)

        # Filter short segments before resampling
        keep = np.concatenate(([True], seg_len > self._min_seg_len_m))
        if np.sum(keep) < 2:
            self._last_reject_reason = "degenerate geometry (<2 valid segments)"
            return False

        xs, ys, zs, ts, s_raw = (
            xs[keep], ys[keep], zs[keep], ts[keep], s_raw[keep],
        )

        total_length = float(s_raw[-1])
        if total_length < self._resample_spacing_m:
            self._last_reject_reason = (
                f"lap too short ({total_length:.0f} m < resample spacing "
                f"{self._resample_spacing_m:.0f} m)"
            )
            return False  # Lap too short

        # -- Uniform arc-length resampling ----------------------------------
        num_points = max(2, int(total_length / self._resample_spacing_m) + 1)
        s_uniform = np.linspace(0.0, total_length, num_points, dtype=np.float32)

        xs = np.interp(s_uniform, s_raw, xs).astype(np.float32)
        ys = np.interp(s_uniform, s_raw, ys).astype(np.float32)
        zs = np.interp(s_uniform, s_raw, zs).astype(np.float32)
        ts = np.interp(s_uniform, s_raw, ts).astype(np.float32)
        s = s_uniform

        # -- Reference selection gating -------------------------------------
        cand_lap_time = float(lap_time) if lap_time > 0.0 else float(ts[-1])

        # Pin the trajectory's final time to the true full-lap duration.
        # The recorder's last point can be up to max_step_m / v_car seconds
        # before the S/F crossing, leaving traj.times[-1] short. Without this,
        # the prediction (ref_lap_time + delta) and the fastest-lap gate both
        # use the truncated time, making the prediction wrong and the gate
        # unreachable for any real follow-up lap.
        if lap_time > 0.0:
            ts[-1] = np.float32(cand_lap_time)

        # -- Build new trajectory -------------------------------------------
        points = np.column_stack((xs, ys, zs))
        new_traj = ReferenceTrajectory(
            s=s, times=ts, points=points,
        )
        new_traj.version = self._next_version
        self._next_version += 1

        # Previous-lap slot: every clean lap replaces it, so a bad lap only
        # lasts until the next one.
        self._last_traj = new_traj

        # Fastest slot: gated. The plausibility gate rejects a glitch-fast
        # candidate (mis-fired lap transition, a lap whose recording was cut
        # short, a track-cut shortcut) before it can lock itself in — nothing
        # slower would ever beat it, so a corrupt fast lap would poison the
        # slot for the rest of the session. The gate applies in every mode:
        # the slot must stay trustworthy for a later switch to fastest-only.
        best = self._best_lap_time_s
        best_reject: Optional[str] = None
        if (
            best is not None
            and self._min_lap_fraction > 0.0
            and cand_lap_time < best * self._min_lap_fraction
        ):
            best_reject = (
                f"implausibly fast ({cand_lap_time:.1f}s < "
                f"{self._min_lap_fraction:.0%} of reference {best:.1f}s)"
            )
        elif best is not None and cand_lap_time >= best - 1e-3:
            best_reject = (
                f"not faster than reference ({cand_lap_time:.1f}s ≥ {best:.1f}s)"
            )
        else:
            self._best_traj = new_traj
            self._best_lap_time_s = cand_lap_time

        # Adoption is judged against the ACTIVE slot: in fastest-only mode a
        # lap that didn't improve the best changes nothing visible (the
        # previous-lap slot was still refreshed for a later mode switch).
        if self._use_fastest_only and best_reject is not None:
            self._last_reject_reason = best_reject
            return False

        self._last_reject_reason = None
        return True
