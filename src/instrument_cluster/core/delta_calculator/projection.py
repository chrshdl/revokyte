"""Reference-lap geometry and point-to-trajectory projection.

Holds the immutable per-lap geometry (segment vectors, arc-length, time
spline, KDTree) and the search that maps a live car position onto it. This is
the spatial half of the delta calculation; the temporal comparison lives in
:mod:`delta_calculator.calculator`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .math_lite import KDTree, PchipInterpolator

# Numerical stability epsilon for segment projection (prevents division by zero)
_EPSILON_SQUARED = 1e-12


@dataclass(slots=True)
class ProjectionResult:
    """Holds the result of a point projection onto the reference line."""

    s: float
    dist_h: float  # Horizontal distance (x, z)
    dist_3d: float  # 3D distance (x, y, z)
    seg_idx: int
    t_seg: float  # Normalized t (0.0 to 1.0) along the segment
    point_on_line: np.ndarray  # [x, y, z]
    segment_origin: np.ndarray  # [x, y, z]
    segment_end: np.ndarray  # [x, y, z]


class ReferenceTrajectory:
    """
    Encapsulates the immutable geometry and search structures for a reference lap.
    """

    def __init__(
        self,
        s: np.ndarray,
        times: np.ndarray,
        points: np.ndarray,  # (N, 3) array of x, y, z
        closed: Optional[bool] = None,
        close_gap_frac: float = 0.1,
    ):
        self.s = s
        self.times = times
        self.lap_length = float(s[-1])
        self.version = 0  # Can be incremented externally

        # Closed-loop detection. A race circuit starts and finishes at the same
        # place, so the first and last recorded points sit a seam apart (a few
        # metres across the start/finish line). A point-to-point course
        # (hillclimb, sprint) does not. When closed, segment search and
        # arc-length continuity wrap around the seam instead of treating s=0 and
        # s=lap_length as far-apart ends of an open polyline.
        if closed is None:
            gap = math.hypot(
                float(points[0, 0] - points[-1, 0]),
                float(points[0, 2] - points[-1, 2]),
            )
            closed = self.lap_length > 0.0 and gap <= close_gap_frac * self.lap_length
        self.closed = bool(closed)

        # Build Time-Reference Spline
        self.tref_spline = PchipInterpolator(s, times, extrapolate=True)

        # Pre-calculate segment geometry
        # Points: 0 to N-1
        self.seg_p0 = points[:-1]  # (N-1, 3)
        self.seg_vec = np.diff(points, axis=0)  # (N-1, 3) vector (dx, dy, dz)

        # Segment Lengths
        self.seg_len_sq = np.sum(self.seg_vec**2, axis=1)
        self.seg_len = np.sqrt(self.seg_len_sq)
        self.seg_s0 = s[:-1]

        # Filter valid segments for projection (avoid divide by zero)
        valid_mask = self.seg_len > 1e-6
        self.valid_indices = np.where(valid_mask)[0]

        # Build KDTree on Midpoints (X, Z only) for lateral lookup
        # mids = p0 + 0.5 * vec
        mids_3d = self.seg_p0[valid_mask] + 0.5 * self.seg_vec[valid_mask]
        mids_2d = mids_3d[:, [0, 2]]  # Extract X and Z
        self.tree = KDTree(mids_2d)

        # Map KDTree indices back to original segment indices
        self.tree_idx_to_seg_idx = self.valid_indices

    def get_time_at_s(self, s: float) -> float:
        return float(self.tref_spline(s))

    def _project_to_candidates(
        self, q_point: np.ndarray, candidates: set
    ) -> Optional[ProjectionResult]:
        """
        Projects a 3D query point onto a specific set of candidate segments.
        Returns the best projection result.
        """
        best_res: Optional[ProjectionResult] = None
        min_d3 = float("inf")

        for idx in candidates:
            p0 = self.seg_p0[idx]
            vec = self.seg_vec[idx]  # dx, dy, dz
            L = self.seg_len[idx]

            # Vector from segment start to query point
            v_q = q_point - p0

            # Project v_q onto vec to find t (normalized 0..1)
            # Epsilon prevents division by zero on degenerate segments;
            # when L≈0, vec≈[0,0,0] so dot→0 and t→0, projecting to p0.
            t = np.dot(v_q, vec) / (L * L + _EPSILON_SQUARED)
            t = max(0.0, min(1.0, float(t)))

            # Calculate nearest point on line
            closest = p0 + t * vec

            # Distances
            d_vec = q_point - closest
            d3 = float(np.linalg.norm(d_vec))
            dh = math.hypot(d_vec[0], d_vec[2])  # Horizontal X, Z

            if d3 < min_d3:
                min_d3 = d3
                s_total = float(self.seg_s0[idx] + t * L)

                best_res = ProjectionResult(
                    s=s_total,
                    dist_h=dh,
                    dist_3d=d3,
                    seg_idx=int(idx),
                    t_seg=t,
                    point_on_line=closest,
                    segment_origin=p0,
                    segment_end=p0 + vec,
                )

        return best_res

    def project(
        self, q_point: np.ndarray,
    ) -> Optional[ProjectionResult]:
        """
        Projects a 3D query point onto the trajectory using KDTree search.
        q_point: [x, y, z]
        """
        if len(self.valid_indices) == 0:
            return None

        qx, qz = q_point[0], q_point[2]

        # 1. Query KDTree (X, Z only)
        _, tree_idx = self.tree.query((qx, qz), k=1)

        # Convert tree index to actual segment index
        center_seg_idx = self.tree_idx_to_seg_idx[int(tree_idx)]
        num_segs = len(self.seg_p0)

        # 2. Select Candidates: Center, Previous, Next. On a closed loop the
        # neighbours wrap across the seam so the segment before seg 0 is the
        # last segment, and vice versa.
        candidates = {center_seg_idx}
        if self.closed:
            candidates.add((center_seg_idx - 1) % num_segs)
            candidates.add((center_seg_idx + 1) % num_segs)
        else:
            if center_seg_idx > 0:
                candidates.add(center_seg_idx - 1)
            if center_seg_idx + 1 < num_segs:
                candidates.add(center_seg_idx + 1)

        # 3. Find Best Projection among candidates
        return self._project_to_candidates(q_point, candidates)

    def project_constrained(
        self,
        q_point: np.ndarray,
        last_seg_idx: int,
        max_seg_jump: int = 5,
    ) -> Optional[ProjectionResult]:
        """
        Projects a 3D query point using constrained segment search.
        Only searches within max_seg_jump segments of last_seg_idx.
        This prevents incorrect matching when off-track near other parts of the circuit.
        """
        num_segs = len(self.seg_p0)

        # Build candidate set within the constrained range. On a closed loop the
        # window wraps modulo num_segs so the search can follow the car across
        # the start/finish seam (e.g. the last segment into the first).
        if self.closed:
            candidates = {
                (last_seg_idx + d) % num_segs
                for d in range(-max_seg_jump, max_seg_jump + 1)
            }
        else:
            start_idx = max(0, last_seg_idx - max_seg_jump)
            end_idx = min(num_segs, last_seg_idx + max_seg_jump + 1)
            candidates = set(range(start_idx, end_idx))

        return self._project_to_candidates(q_point, candidates)
